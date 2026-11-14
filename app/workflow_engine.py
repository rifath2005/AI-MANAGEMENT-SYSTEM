"""Workflow routing, multi-level sequential/parallel execution, notifications, and reminders."""

import json
import os
from datetime import datetime, timezone

from .ai_engine import ai_engine
from .currency import to_usd
from .db import append_audit_log, utcnow_iso

REJECTION_REASONS = [
    {"code": "MISSING_DOCS", "label": "Missing or Illegible Receipts / Documentation"},
    {"code": "BUDGET_EXCEEDED", "label": "Exceeds Allocated Departmental Budget"},
    {"code": "POLICY_VIOLATION", "label": "Company Policy Violation / Prohibited Expense"},
    {"code": "UNAPPROVED_VENDOR", "label": "Unapproved Vendor or Procurement Channel"},
    {"code": "DUPLICATE_SUBMISSION", "label": "Duplicate Request Submission"},
    {"code": "WITHDRAWN_BY_REQUESTER", "label": "Withdrawn by Requester"},
    {"code": "OTHER", "label": "Other Discretionary Reason (See Comment)"},
]


def get_rejection_reason_label(code: str | None) -> str:
    if not code:
        return "Discretionary"
    for r in REJECTION_REASONS:
        if r["code"].lower() == str(code).lower():
            return r["label"]
    return str(code)


def dispatch_email(
    db,
    recipient_email: str,
    recipient_name: str,
    subject: str,
    body: str,
    category: str = "general",
    request_id: int | None = None,
):
    if not recipient_email:
        return
    now = utcnow_iso()
    delivery_status = "simulated"

    smtp_host = os.environ.get("SMTP_HOST")
    if smtp_host:
        try:
            import smtplib
            from email.mime.text import MIMEText

            smtp_port = int(os.environ.get("SMTP_PORT", 587))
            smtp_user = os.environ.get("SMTP_USER")
            smtp_pass = os.environ.get("SMTP_PASS")
            sender = os.environ.get("SMTP_FROM", "noreply@ams-enterprise.com")

            msg = MIMEText(body, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = sender
            msg["To"] = recipient_email

            with smtplib.SMTP(smtp_host, smtp_port, timeout=3) as server:
                if os.environ.get("SMTP_USE_TLS", "true").lower() in ("true", "1"):
                    server.starttls()
                if smtp_user and smtp_pass:
                    server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            delivery_status = "sent"
        except Exception:
            delivery_status = "failed"

    try:
        db.execute(
            """
            INSERT INTO email_dispatches (recipient_email, recipient_name, subject, body, category, request_id, delivery_status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (recipient_email, recipient_name or recipient_email, subject, body, category, request_id, delivery_status, now),
        )
    except Exception:
        pass


def _notify_role(db, role: str, request_id: int, category: str, title: str, message: str):
    users = db.execute("SELECT id, email, full_name FROM users WHERE role = ? AND is_active = 1", (role,)).fetchall()
    now = utcnow_iso()
    for u in users:
        db.execute(
            """
            INSERT INTO notifications (user_id, request_id, category, title, message, is_read, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (u["id"], request_id, category, title, message, now),
        )
        dispatch_email(db, u["email"], u["full_name"], title, message, category, request_id)


def _notify_user(db, user_id: int, request_id: int, category: str, title: str, message: str):
    user = db.execute("SELECT email, full_name FROM users WHERE id = ?", (user_id,)).fetchone()
    now = utcnow_iso()
    db.execute(
        """
        INSERT INTO notifications (user_id, request_id, category, title, message, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (user_id, request_id, category, title, message, now),
    )
    if user:
        dispatch_email(db, user["email"], user["full_name"], title, message, category, request_id)


def select_workflow(db, request_type: str, amount: float) -> dict | None:
    row = db.execute(
        """
        SELECT * FROM workflows
        WHERE request_type = ? AND is_active = 1 AND min_amount <= ? AND max_amount >= ?
        ORDER BY id ASC LIMIT 1
        """,
        (request_type, amount, amount),
    ).fetchone()
    if not row:
        row = db.execute(
            "SELECT * FROM workflows WHERE request_type = ? AND is_active = 1 ORDER BY id ASC LIMIT 1",
            (request_type,),
        ).fetchone()
    return dict(row) if row else None


def submit_and_route_request(db, user: dict, payload: dict, has_attachment: bool = False) -> dict:
    """Create a request, run AI & policy evaluation, and route or auto-approve."""
    now = utcnow_iso()
    request_type = payload.get("request_type", "expense_report")
    amount = float(payload.get("amount") or 0.0)
    currency = (payload.get("currency") or "USD").upper()
    amount_usd = to_usd(amount, currency)
    title = payload.get("title", "").strip()
    description = payload.get("description", "").strip()
    department = payload.get("department") or user.get("department") or "General"
    urgency = payload.get("urgency") or "normal"
    is_draft = bool(payload.get("is_draft"))

    if is_draft:
        cur = db.execute(
            """
            INSERT INTO requests (
                requester_id, request_type, title, description, amount, currency, department, urgency,
                status, workflow_id, current_stage_index, ai_recommendation, ai_confidence, ai_risk_score,
                ai_explanation, is_anomaly, anomaly_score, anomaly_reasons_json, nlp_extracted_json,
                auto_approved, due_at, amount_usd, is_draft, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, 0, 'draft', 1.0, 0.1, 'Saved as Draft', 0, 0, '[]', '{}', 0, NULL, ?, 1, ?, ?)
            """,
            (user["id"], request_type, title, description, amount, currency, department, urgency, amount_usd, now, now),
        )
        req_id = cur.lastrowid
        append_audit_log(
            db,
            user["id"],
            user["username"],
            "REQUEST_DRAFT_SAVED",
            "request",
            req_id,
            {"title": title, "amount": amount, "currency": currency, "amount_usd": amount_usd},
            now,
        )
        db.commit()
        return {"request_id": req_id, "status": "draft", "is_draft": True}

    ai_eval = ai_engine.evaluate_request(
        db,
        {
            "request_type": request_type,
            "title": title,
            "description": description,
            "amount": amount,
            "currency": currency,
            "urgency": urgency,
        },
        has_attachment=has_attachment,
    )

    workflow = select_workflow(db, request_type, amount_usd)
    wf_id = workflow["id"] if workflow else None
    sla_hours = int(workflow["sla_hours"]) if workflow else 48
    due_at = utcnow_iso(offset_hours=sla_hours)

    if ai_eval["auto_approve_eligible"]:
        initial_status = "approved"
    elif ai_eval["is_anomaly"]:
        initial_status = "flagged"
    else:
        initial_status = "in_review" if workflow else "pending"

    cur = db.execute(
        """
        INSERT INTO requests (
            requester_id, request_type, title, description, amount, currency, department, urgency,
            status, workflow_id, current_stage_index, ai_recommendation, ai_confidence, ai_risk_score,
            ai_explanation, is_anomaly, anomaly_score, anomaly_reasons_json, nlp_extracted_json,
            auto_approved, due_at, amount_usd, is_draft, created_at, updated_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
        """,
        (
            user["id"],
            request_type,
            title,
            description,
            amount,
            currency,
            department,
            urgency,
            initial_status,
            wf_id,
            ai_eval["recommendation"],
            ai_eval["confidence"],
            ai_eval["risk_score"],
            ai_eval["explanation"],
            1 if ai_eval["is_anomaly"] else 0,
            ai_eval["anomaly_score"],
            json.dumps(ai_eval["anomaly_reasons"]),
            json.dumps(ai_eval["nlp_extracted"]),
            1 if ai_eval["auto_approve_eligible"] else 0,
            due_at,
            amount_usd,
            now,
            now,
            now if ai_eval["auto_approve_eligible"] else None,
        ),
    )
    req_id = cur.lastrowid

    append_audit_log(
        db,
        user["id"],
        user["username"],
        "REQUEST_SUBMITTED",
        "request",
        req_id,
        {
            "request_type": request_type,
            "amount": amount,
            "currency": currency,
            "amount_usd": amount_usd,
            "status": initial_status,
            "is_anomaly": ai_eval["is_anomaly"],
            "auto_approved": ai_eval["auto_approve_eligible"],
        },
        now,
    )

    if ai_eval["auto_approve_eligible"]:
        db.execute(
            """
            INSERT INTO approvals (request_id, task_id, approver_id, decision, comment, cycle_time_hours, created_at)
            VALUES (?, NULL, ?, 'auto_approved', ?, 0.0, ?)
            """,
            (req_id, user["id"], "Automated approval for routine/low-risk request", now),
        )
        _notify_user(
            db,
            user["id"],
            req_id,
            "status_update",
            f"Auto-Approved: {title}",
            f"Request #{req_id} ({amount} {currency}) was automatically approved under low-risk policy rules.",
        )
        append_audit_log(
            db,
            user["id"],
            "ai_rule_engine",
            "REQUEST_AUTO_APPROVED",
            "request",
            req_id,
            {"risk_score": ai_eval["risk_score"], "amount": amount, "amount_usd": amount_usd},
            now,
        )
    elif workflow:
        stages = json.loads(workflow["stages_json"])
        mode = workflow["execution_mode"]
        for idx, stage in enumerate(stages):
            stage_status = "pending" if (mode == "parallel" or idx == 0) else "waiting"
            stage_sla = int(stage.get("sla_hours", sla_hours))
            stage_due = utcnow_iso(offset_hours=stage_sla)
            db.execute(
                """
                INSERT INTO approval_tasks (request_id, stage_index, stage_name, assigned_role, status, due_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (req_id, idx, stage["name"], stage["role"], stage_status, stage_due, now),
            )
            if stage_status == "pending":
                _notify_role(
                    db,
                    stage["role"],
                    req_id,
                    "action_required",
                    f"Approval Needed: {title}",
                    f"Request #{req_id} ({request_type}, {amount} {currency}) awaits {stage['name']}.",
                )

    if ai_eval["is_anomaly"]:
        reasons_txt = "; ".join(ai_eval["anomaly_reasons"])
        for role in ("approver", "admin"):
            _notify_role(
                db,
                role,
                req_id,
                "anomaly_alert",
                f"Anomaly Alert: Request #{req_id}",
                f"{title} ({amount} {currency}) flagged by AI anomaly detector: {reasons_txt}",
            )
        append_audit_log(
            db,
            user["id"],
            "ai_anomaly_detector",
            "ANOMALY_FLAGGED",
            "request",
            req_id,
            {"anomaly_score": ai_eval["anomaly_score"], "reasons": ai_eval["anomaly_reasons"]},
            now,
        )

    db.commit()
    return {"request_id": req_id, "status": initial_status, "ai_evaluation": ai_eval}


def submit_draft(db, user: dict, request_id: int) -> tuple[dict, int]:
    """Submit a previously saved draft request into the active routing pipeline."""
    req_row = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not req_row:
        return {"error": "Request not found"}, 404
    req = dict(req_row)
    if not req.get("is_draft"):
        return {"error": "Request is not a draft"}, 400
    if req["requester_id"] != user["id"] and user["role"] != "admin":
        return {"error": "Access denied"}, 403

    now = utcnow_iso()
    request_type = req["request_type"]
    amount = float(req["amount"])
    currency = req["currency"]
    amount_usd = to_usd(amount, currency)
    has_attachment = bool(
        db.execute("SELECT COUNT(*) AS c FROM request_attachments WHERE request_id = ?", (request_id,)).fetchone()["c"]
    )

    ai_eval = ai_engine.evaluate_request(
        db,
        {
            "request_type": request_type,
            "title": req["title"],
            "description": req["description"],
            "amount": amount,
            "currency": currency,
            "urgency": req["urgency"],
        },
        has_attachment=has_attachment,
    )

    workflow = select_workflow(db, request_type, amount_usd)
    wf_id = workflow["id"] if workflow else None
    sla_hours = int(workflow["sla_hours"]) if workflow else 48
    due_at = utcnow_iso(offset_hours=sla_hours)

    if ai_eval["auto_approve_eligible"]:
        new_status = "approved"
    elif ai_eval["is_anomaly"]:
        new_status = "flagged"
    else:
        new_status = "in_review" if workflow else "pending"

    db.execute(
        """
        UPDATE requests
        SET is_draft = 0, status = ?, workflow_id = ?, due_at = ?, amount_usd = ?,
            ai_recommendation = ?, ai_confidence = ?, ai_risk_score = ?, ai_explanation = ?,
            is_anomaly = ?, anomaly_score = ?, anomaly_reasons_json = ?, nlp_extracted_json = ?,
            auto_approved = ?, updated_at = ?, completed_at = ?
        WHERE id = ?
        """,
        (
            new_status,
            wf_id,
            due_at,
            amount_usd,
            ai_eval["recommendation"],
            ai_eval["confidence"],
            ai_eval["risk_score"],
            ai_eval["explanation"],
            1 if ai_eval["is_anomaly"] else 0,
            ai_eval["anomaly_score"],
            json.dumps(ai_eval["anomaly_reasons"]),
            json.dumps(ai_eval["nlp_extracted"]),
            1 if ai_eval["auto_approve_eligible"] else 0,
            now,
            now if ai_eval["auto_approve_eligible"] else None,
            request_id,
        ),
    )

    append_audit_log(
        db, user["id"], user["username"], "REQUEST_DRAFT_SUBMITTED", "request", request_id,
        {"status": new_status, "amount": amount, "currency": currency}, now,
    )

    if ai_eval["auto_approve_eligible"]:
        db.execute(
            """
            INSERT INTO approvals (request_id, task_id, approver_id, decision, comment, cycle_time_hours, created_at)
            VALUES (?, NULL, ?, 'auto_approved', ?, 0.0, ?)
            """,
            (request_id, user["id"], "Automated approval for routine/low-risk request", now),
        )
        _notify_user(
            db,
            user["id"],
            request_id,
            "status_update",
            f"Auto-Approved: {req['title']}",
            f"Request #{request_id} ({amount} {currency}) was automatically approved.",
        )
    elif workflow:
        stages = json.loads(workflow["stages_json"])
        mode = workflow["execution_mode"]
        for idx, stage in enumerate(stages):
            stage_status = "pending" if (mode == "parallel" or idx == 0) else "waiting"
            stage_sla = int(stage.get("sla_hours", sla_hours))
            stage_due = utcnow_iso(offset_hours=stage_sla)
            db.execute(
                """
                INSERT INTO approval_tasks (request_id, stage_index, stage_name, assigned_role, status, due_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (request_id, idx, stage["name"], stage["role"], stage_status, stage_due, now),
            )
            if stage_status == "pending":
                _notify_role(
                    db,
                    stage["role"],
                    request_id,
                    "action_required",
                    f"Approval Needed: {req['title']}",
                    f"Request #{request_id} awaits {stage['name']}.",
                )

    db.commit()
    return {"request_id": request_id, "status": new_status, "ai_evaluation": ai_eval}, 200


def withdraw_request(db, user: dict, request_id: int) -> tuple[dict, int]:
    """Allow requester to cancel/withdraw a pending request."""
    req_row = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not req_row:
        return {"error": "Request not found"}, 404
    req = dict(req_row)

    if req["requester_id"] != user["id"] and user["role"] != "admin":
        return {"error": "Access denied: only the requester or an administrator can withdraw this request"}, 403

    if req["status"] in ("approved", "rejected") or req.get("is_withdrawn"):
        return {"error": f"Request cannot be withdrawn because it is already {req['status']}"}, 400

    now = utcnow_iso()
    db.execute(
        """
        UPDATE requests
        SET status = 'rejected', is_withdrawn = 1, rejection_reason = 'WITHDRAWN_BY_REQUESTER',
            completed_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, now, request_id),
    )
    db.execute(
        """
        UPDATE approval_tasks
        SET status = 'skipped', comment = 'Request withdrawn by requester'
        WHERE request_id = ? AND status IN ('pending', 'waiting')
        """,
        (request_id,),
    )
    append_audit_log(
        db, user["id"], user["username"], "REQUEST_WITHDRAWN", "request", request_id,
        {"title": req["title"], "amount": req["amount"]}, now,
    )
    _notify_user(
        db,
        user["id"],
        request_id,
        "status_update",
        f"Request #{request_id} Withdrawn",
        f"You successfully withdrew your request '{req['title']}'.",
    )
    db.commit()
    return {"request_id": request_id, "status": "withdrawn", "is_withdrawn": True}, 200


def process_approval_decision(
    db, actor: dict, request_id: int, decision: str, comment: str = "", rejection_reason: str | None = None
) -> tuple[dict, int]:
    """Process an approver's approve/reject action on a request, supporting delegation & rejection taxonomy."""
    if decision not in ("approved", "rejected"):
        return {"error": "Decision must be 'approved' or 'rejected'"}, 400

    req_row = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not req_row:
        return {"error": "Request not found"}, 404
    req = dict(req_row)

    if req["status"] in ("approved", "rejected") or req.get("is_withdrawn"):
        return {"error": f"Request is already {req['status']}"}, 400

    if req["requester_id"] == actor["id"] and actor["role"] != "admin":
        return {"error": "Requesters cannot approve or reject their own request"}, 403

    # Find pending task matching actor's role OR active delegation
    task_row = None
    delegated_by_user = None

    if actor["role"] == "admin":
        task_row = db.execute(
            "SELECT * FROM approval_tasks WHERE request_id = ? AND status = 'pending' ORDER BY stage_index ASC LIMIT 1",
            (request_id,),
        ).fetchone()
    else:
        # 1. Direct role match
        task_row = db.execute(
            "SELECT * FROM approval_tasks WHERE request_id = ? AND status = 'pending' AND assigned_role = ? ORDER BY stage_index ASC LIMIT 1",
            (request_id, actor["role"]),
        ).fetchone()

        # 2. Out-of-office delegation match
        if not task_row:
            today = utcnow_iso()[:10]
            del_rows = db.execute(
                """
                SELECT u.id, u.username, u.full_name, u.role
                FROM delegations d
                JOIN users u ON u.id = d.user_id
                WHERE d.delegate_user_id = ?
                  AND d.is_active = 1
                  AND date(d.start_date) <= date(?)
                  AND date(d.end_date) >= date(?)
                """,
                (actor["id"], today, today),
            ).fetchall()
            for du in del_rows:
                cand = db.execute(
                    "SELECT * FROM approval_tasks WHERE request_id = ? AND status = 'pending' AND assigned_role = ? ORDER BY stage_index ASC LIMIT 1",
                    (request_id, du["role"]),
                ).fetchone()
                if cand:
                    task_row = cand
                    delegated_by_user = du
                    break

    if not task_row:
        return {"error": f"No pending approval task assigned to role '{actor['role']}' for request #{request_id}"}, 403

    task = dict(task_row)
    now = utcnow_iso()
    created_dt = datetime.fromisoformat(task["created_at"])
    cycle_hours = round(max((datetime.now(timezone.utc) - created_dt).total_seconds() / 3600.0, 0.01), 2)

    final_comment = comment
    if delegated_by_user:
        prefix = f"[Delegated for {delegated_by_user['full_name']}]"
        final_comment = f"{prefix} {comment}".strip() if comment else prefix

    reason_code = rejection_reason if decision == "rejected" else None
    reason_label = get_rejection_reason_label(reason_code) if reason_code else None

    db.execute(
        """
        UPDATE approval_tasks
        SET status = ?, decision_by = ?, comment = ?, decided_at = ?
        WHERE id = ?
        """,
        (decision, actor["id"], final_comment, now, task["id"]),
    )
    db.execute(
        """
        INSERT INTO approvals (request_id, task_id, approver_id, decision, rejection_reason, comment, cycle_time_hours, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (request_id, task["id"], actor["id"], decision, reason_code, final_comment, cycle_hours, now),
    )

    if decision == "rejected":
        db.execute(
            "UPDATE approval_tasks SET status = 'skipped' WHERE request_id = ? AND status IN ('pending', 'waiting')",
            (request_id,),
        )
        db.execute(
            "UPDATE requests SET status = 'rejected', rejection_reason = ?, updated_at = ?, completed_at = ? WHERE id = ?",
            (reason_code, now, now, request_id),
        )
        reason_txt = f" Reason: {reason_label}." if reason_label else ""
        _notify_user(
            db,
            req["requester_id"],
            request_id,
            "status_update",
            f"Request #{request_id} Rejected",
            f"Your request '{req['title']}' was rejected at {task['stage_name']}.{reason_txt} Comment: {final_comment or 'None'}",
        )
        new_status = "rejected"
    else:
        # Check if any waiting stage (sequential) or remaining pending tasks (parallel) exist
        next_waiting = db.execute(
            "SELECT * FROM approval_tasks WHERE request_id = ? AND status = 'waiting' ORDER BY stage_index ASC LIMIT 1",
            (request_id,),
        ).fetchone()
        remaining_pending = db.execute(
            "SELECT COUNT(*) AS c FROM approval_tasks WHERE request_id = ? AND status = 'pending'",
            (request_id,),
        ).fetchone()["c"]

        if next_waiting:
            db.execute(
                "UPDATE approval_tasks SET status = 'pending' WHERE id = ?",
                (next_waiting["id"],),
            )
            db.execute(
                "UPDATE requests SET status = 'in_review', current_stage_index = ?, updated_at = ? WHERE id = ?",
                (next_waiting["stage_index"], now, request_id),
            )
            _notify_role(
                db,
                next_waiting["assigned_role"],
                request_id,
                "action_required",
                f"Approval Needed: {req['title']}",
                f"Request #{request_id} advanced to {next_waiting['stage_name']}.",
            )
            _notify_user(
                db,
                req["requester_id"],
                request_id,
                "status_update",
                f"Request #{request_id} Stage Approved",
                f"{task['stage_name']} approved. Now awaiting {next_waiting['stage_name']}.",
            )
            new_status = "in_review"
        elif remaining_pending > 0:
            db.execute(
                "UPDATE requests SET status = 'in_review', updated_at = ? WHERE id = ?",
                (now, request_id),
            )
            new_status = "in_review"
        else:
            db.execute(
                "UPDATE requests SET status = 'approved', updated_at = ?, completed_at = ? WHERE id = ?",
                (now, now, request_id),
            )
            _notify_user(
                db,
                req["requester_id"],
                request_id,
                "status_update",
                f"Request #{request_id} Approved",
                f"Your request '{req['title']}' has completed all approval stages.",
            )
            new_status = "approved"

    audit_details = {
        "task_id": task["id"],
        "stage_name": task["stage_name"],
        "comment": final_comment,
        "resulting_status": new_status,
    }
    if delegated_by_user:
        audit_details["delegated_for"] = delegated_by_user["username"]
    if reason_code:
        audit_details["rejection_reason"] = reason_code

    append_audit_log(
        db,
        actor["id"],
        actor["username"],
        f"TASK_{decision.upper()}",
        "request",
        request_id,
        audit_details,
        now,
    )
    db.commit()
    return {"request_id": request_id, "status": new_status, "stage": task["stage_name"], "decision": decision}, 200


def run_sla_escalation(db) -> dict:
    """Escalate pending tasks that have breached their SLA deadline (Auto-Escalation Engine)."""
    now_iso = utcnow_iso()
    overdue_tasks = db.execute(
        """
        SELECT t.id AS task_id, t.request_id, t.stage_name, t.assigned_role, t.due_at,
               r.title, r.amount, r.currency, r.requester_id
        FROM approval_tasks t
        JOIN requests r ON r.id = t.request_id
        WHERE t.status = 'pending' AND t.due_at IS NOT NULL AND t.due_at < ? AND t.is_escalated = 0
        """,
        (now_iso,),
    ).fetchall()

    escalated_count = 0
    now = utcnow_iso()
    for t in overdue_tasks:
        db.execute("UPDATE approval_tasks SET is_escalated = 1 WHERE id = ?", (t["task_id"],))
        db.execute("UPDATE requests SET urgency = 'urgent' WHERE id = ?", (t["request_id"],))

        # Notify assigned role and admin of the SLA breach
        _notify_role(
            db,
            t["assigned_role"],
            t["request_id"],
            "sla_escalation",
            f"⚠️ SLA BREACH: Request #{t['request_id']}",
            f"Approval task '{t['stage_name']}' is overdue (SLA deadline was {t['due_at'][:16]}Z). Ticket escalated to Urgent.",
        )
        _notify_role(
            db,
            "admin",
            t["request_id"],
            "sla_escalation",
            f"🚨 Escalated Request: #{t['request_id']} ({t['title']})",
            f"Stage '{t['stage_name']}' assigned to '{t['assigned_role']}' breached SLA deadline.",
        )
        append_audit_log(
            db,
            None,
            "sla_escalation_engine",
            "TASK_SLA_ESCALATED",
            "task",
            t["task_id"],
            {"request_id": t["request_id"], "stage_name": t["stage_name"], "due_at": t["due_at"]},
            now,
        )
        escalated_count += 1

    db.commit()
    return {"escalated_count": escalated_count}


def run_reminder_sweep(db) -> dict:
    """Create deadline reminder notifications for overdue or soon-due pending tasks and trigger escalations."""
    # First, run SLA escalation sweep
    escalation_res = run_sla_escalation(db)

    now = datetime.now(timezone.utc)
    soon_cutoff = utcnow_iso(offset_hours=12)
    pending_tasks = db.execute(
        """
        SELECT t.id AS task_id, t.request_id, t.stage_name, t.assigned_role, t.due_at, r.title
        FROM approval_tasks t
        JOIN requests r ON r.id = t.request_id
        WHERE t.status = 'pending' AND t.due_at IS NOT NULL AND t.due_at <= ?
        """,
        (soon_cutoff,),
    ).fetchall()

    sent = 0
    for t in pending_tasks:
        is_overdue = datetime.fromisoformat(t["due_at"]) < now
        label = "OVERDUE" if is_overdue else "Due Soon"
        users = db.execute("SELECT id FROM users WHERE role = ? AND is_active = 1", (t["assigned_role"],)).fetchall()
        for u in users:
            existing = db.execute(
                """
                SELECT id FROM notifications
                WHERE user_id = ? AND request_id = ? AND category = 'deadline_reminder' AND is_read = 0
                """,
                (u["id"], t["request_id"]),
            ).fetchone()
            if not existing:
                _notify_user(
                    db,
                    u["id"],
                    t["request_id"],
                    "deadline_reminder",
                    f"{label}: {t['title']}",
                    f"Pending {t['stage_name']} for Request #{t['request_id']} (due {t['due_at'][:16]}Z).",
                )
                sent += 1
    db.commit()
    return {
        "checked_tasks": len(pending_tasks),
        "reminders_sent": sent,
        "escalated_count": escalation_res["escalated_count"],
    }
