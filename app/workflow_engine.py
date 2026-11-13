"""Workflow routing, multi-level sequential/parallel execution, notifications, and reminders."""

import json
from datetime import datetime, timezone

from .ai_engine import ai_engine
from .db import append_audit_log, utcnow_iso


def _notify_role(db, role: str, request_id: int, category: str, title: str, message: str):
    users = db.execute("SELECT id FROM users WHERE role = ? AND is_active = 1", (role,)).fetchall()
    now = utcnow_iso()
    for u in users:
        db.execute(
            """
            INSERT INTO notifications (user_id, request_id, category, title, message, is_read, created_at)
            VALUES (?, ?, ?, ?, ?, 0, ?)
            """,
            (u["id"], request_id, category, title, message, now),
        )


def _notify_user(db, user_id: int, request_id: int, category: str, title: str, message: str):
    db.execute(
        """
        INSERT INTO notifications (user_id, request_id, category, title, message, is_read, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        """,
        (user_id, request_id, category, title, message, utcnow_iso()),
    )


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
    title = payload.get("title", "").strip()
    description = payload.get("description", "").strip()
    department = payload.get("department") or user.get("department") or "General"
    urgency = payload.get("urgency") or "normal"
    currency = payload.get("currency") or "USD"

    ai_eval = ai_engine.evaluate_request(
        db,
        {
            "request_type": request_type,
            "title": title,
            "description": description,
            "amount": amount,
            "urgency": urgency,
        },
        has_attachment=has_attachment,
    )

    workflow = select_workflow(db, request_type, amount)
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
            auto_approved, due_at, created_at, updated_at, completed_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            {"risk_score": ai_eval["risk_score"], "amount": amount},
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


def process_approval_decision(db, actor: dict, request_id: int, decision: str, comment: str = "") -> tuple[dict, int]:
    """Process an approver's approve/reject action on a request."""
    if decision not in ("approved", "rejected"):
        return {"error": "Decision must be 'approved' or 'rejected'"}, 400

    req_row = db.execute("SELECT * FROM requests WHERE id = ?", (request_id,)).fetchone()
    if not req_row:
        return {"error": "Request not found"}, 404
    req = dict(req_row)

    if req["status"] in ("approved", "rejected"):
        return {"error": f"Request is already {req['status']}"}, 400

    if req["requester_id"] == actor["id"] and actor["role"] != "admin":
        return {"error": "Requesters cannot approve or reject their own request"}, 403

    # Find pending task matching actor's role (or any pending task if admin)
    if actor["role"] == "admin":
        task_row = db.execute(
            "SELECT * FROM approval_tasks WHERE request_id = ? AND status = 'pending' ORDER BY stage_index ASC LIMIT 1",
            (request_id,),
        ).fetchone()
    else:
        task_row = db.execute(
            "SELECT * FROM approval_tasks WHERE request_id = ? AND status = 'pending' AND assigned_role = ? ORDER BY stage_index ASC LIMIT 1",
            (request_id, actor["role"]),
        ).fetchone()

    if not task_row:
        return {"error": f"No pending approval task assigned to role '{actor['role']}' for request #{request_id}"}, 403

    task = dict(task_row)
    now = utcnow_iso()
    created_dt = datetime.fromisoformat(task["created_at"])
    cycle_hours = round(max((datetime.now(timezone.utc) - created_dt).total_seconds() / 3600.0, 0.01), 2)

    db.execute(
        """
        UPDATE approval_tasks
        SET status = ?, decision_by = ?, comment = ?, decided_at = ?
        WHERE id = ?
        """,
        (decision, actor["id"], comment, now, task["id"]),
    )
    db.execute(
        """
        INSERT INTO approvals (request_id, task_id, approver_id, decision, comment, cycle_time_hours, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (request_id, task["id"], actor["id"], decision, comment, cycle_hours, now),
    )

    if decision == "rejected":
        db.execute(
            "UPDATE approval_tasks SET status = 'skipped' WHERE request_id = ? AND status IN ('pending', 'waiting')",
            (request_id,),
        )
        db.execute(
            "UPDATE requests SET status = 'rejected', updated_at = ?, completed_at = ? WHERE id = ?",
            (now, now, request_id),
        )
        _notify_user(
            db,
            req["requester_id"],
            request_id,
            "status_update",
            f"Request #{request_id} Rejected",
            f"Your request '{req['title']}' was rejected at {task['stage_name']}. Comment: {comment or 'None'}",
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

    append_audit_log(
        db,
        actor["id"],
        actor["username"],
        f"TASK_{decision.upper()}",
        "request",
        request_id,
        {
            "task_id": task["id"],
            "stage_name": task["stage_name"],
            "comment": comment,
            "resulting_status": new_status,
        },
        now,
    )
    db.commit()
    return {"request_id": request_id, "status": new_status, "stage": task["stage_name"], "decision": decision}, 200


def run_reminder_sweep(db) -> dict:
    """Create deadline reminder notifications for overdue or soon-due pending tasks (FR-10)."""
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
    return {"checked_tasks": len(pending_tasks), "reminders_sent": sent}
