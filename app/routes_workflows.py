"""Workflow definitions, policy/rule management, notifications, and reminder sweep routes."""

import json
from flask import Blueprint, g, jsonify, request

from .ai_engine import analyze_workflows_and_rules
from .db import append_audit_log, get_db, utcnow_iso
from .security import require_auth, require_roles
from .workflow_engine import run_reminder_sweep

workflows_bp = Blueprint("workflows", __name__, url_prefix="/api")


@workflows_bp.route("/workflows", methods=["GET"])
@require_auth
def list_workflows():
    rows = get_db().execute("SELECT * FROM workflows ORDER BY id ASC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["stages"] = json.loads(d.pop("stages_json"))
        d["is_active"] = bool(d["is_active"])
        result.append(d)
    return jsonify({"workflows": result})


@workflows_bp.route("/workflows", methods=["POST"])
@require_roles("admin")
def create_workflow():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    request_type = (data.get("request_type") or "").strip()
    execution_mode = (data.get("execution_mode") or "sequential").strip().lower()
    stages = data.get("stages") or []
    min_amount = float(data.get("min_amount", 0))
    max_amount = float(data.get("max_amount", 1000000))
    sla_hours = int(data.get("sla_hours", 48))

    if not name or not request_type or not stages:
        return jsonify({"error": "name, request_type, and non-empty stages are required"}), 400
    if execution_mode not in ("sequential", "parallel"):
        return jsonify({"error": "execution_mode must be 'sequential' or 'parallel'"}), 400

    db = get_db()
    if db.execute("SELECT id FROM workflows WHERE name = ?", (name,)).fetchone():
        return jsonify({"error": "Workflow with this name already exists"}), 409

    now = utcnow_iso()
    cur = db.execute(
        """
        INSERT INTO workflows (name, request_type, execution_mode, min_amount, max_amount, stages_json, sla_hours, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (name, request_type, execution_mode, min_amount, max_amount, json.dumps(stages), sla_hours, now),
    )
    wf_id = cur.lastrowid
    append_audit_log(
        db, g.current_user["id"], g.current_user["username"], "WORKFLOW_CREATED", "workflow", wf_id,
        {"name": name, "request_type": request_type, "execution_mode": execution_mode, "stages": stages}, now
    )
    db.commit()
    return jsonify({"id": wf_id, "name": name, "execution_mode": execution_mode}), 201


@workflows_bp.route("/workflows/<int:workflow_id>", methods=["PATCH"])
@require_roles("admin")
def update_workflow(workflow_id: int):
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM workflows WHERE id = ?", (workflow_id,)).fetchone()
    if not row:
        return jsonify({"error": "Workflow not found"}), 404

    execution_mode = data.get("execution_mode", row["execution_mode"])
    if execution_mode not in ("sequential", "parallel"):
        return jsonify({"error": "execution_mode must be 'sequential' or 'parallel'"}), 400

    stages_json = json.dumps(data["stages"]) if "stages" in data else row["stages_json"]
    is_active = 1 if data.get("is_active", row["is_active"]) else 0
    sla_hours = int(data.get("sla_hours", row["sla_hours"]))

    db.execute(
        "UPDATE workflows SET execution_mode = ?, stages_json = ?, is_active = ?, sla_hours = ? WHERE id = ?",
        (execution_mode, stages_json, is_active, sla_hours, workflow_id),
    )
    append_audit_log(
        db, g.current_user["id"], g.current_user["username"], "WORKFLOW_UPDATED", "workflow", workflow_id,
        {"execution_mode": execution_mode, "is_active": is_active, "sla_hours": sla_hours}
    )
    db.commit()
    return jsonify({"id": workflow_id, "execution_mode": execution_mode, "is_active": bool(is_active)})


@workflows_bp.route("/policies", methods=["GET"])
@require_auth
def list_policies():
    rows = get_db().execute("SELECT * FROM policies ORDER BY id ASC").fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d["blocked_keywords"] = json.loads(d.pop("blocked_keywords_json"))
        d["dynamic_adjustment_enabled"] = bool(d["dynamic_adjustment_enabled"])
        d["is_active"] = bool(d["is_active"])
        result.append(d)
    return jsonify({"policies": result})


@workflows_bp.route("/policies/<int:policy_id>", methods=["PATCH"])
@require_roles("admin")
def update_policy(policy_id: int):
    data = request.get_json(silent=True) or {}
    db = get_db()
    row = db.execute("SELECT * FROM policies WHERE id = ?", (policy_id,)).fetchone()
    if not row:
        return jsonify({"error": "Policy not found"}), 404

    auto_max = float(data.get("auto_approve_max_amount", row["auto_approve_max_amount"]))
    attach_above = float(data.get("require_attachment_above", row["require_attachment_above"]))
    max_allowed = float(data.get("max_allowed_amount", row["max_allowed_amount"]))
    blocked = json.dumps(data["blocked_keywords"]) if "blocked_keywords" in data else row["blocked_keywords_json"]
    dyn_enabled = 1 if data.get("dynamic_adjustment_enabled", row["dynamic_adjustment_enabled"]) else 0
    now = utcnow_iso()

    db.execute(
        """
        UPDATE policies
        SET auto_approve_max_amount = ?, require_attachment_above = ?, max_allowed_amount = ?,
            blocked_keywords_json = ?, dynamic_adjustment_enabled = ?, updated_at = ?
        WHERE id = ?
        """,
        (auto_max, attach_above, max_allowed, blocked, dyn_enabled, now, policy_id),
    )
    append_audit_log(
        db, g.current_user["id"], g.current_user["username"], "POLICY_UPDATED", "policy", policy_id,
        {"auto_approve_max_amount": auto_max, "max_allowed_amount": max_allowed}, now
    )
    db.commit()
    return jsonify({"id": policy_id, "auto_approve_max_amount": auto_max, "max_allowed_amount": max_allowed})


@workflows_bp.route("/policies/<int:policy_id>/apply-dynamic-rule", methods=["POST"])
@require_roles("admin")
def apply_dynamic_rule(policy_id: int):
    """Apply AI-recommended dynamic rule adjustment for a policy (AI-12)."""
    db = get_db()
    analysis = analyze_workflows_and_rules(db)
    proposal = next((p for p in analysis["dynamic_rule_proposals"] if p["policy_id"] == policy_id), None)
    if not proposal:
        return jsonify({"error": "No dynamic rule adjustment proposal currently applies to this policy"}), 404

    now = utcnow_iso()
    new_val = proposal["suggested_auto_approve_max"]
    db.execute(
        "UPDATE policies SET auto_approve_max_amount = ?, updated_at = ? WHERE id = ?",
        (new_val, now, policy_id),
    )
    append_audit_log(
        db, g.current_user["id"], g.current_user["username"], "DYNAMIC_RULE_APPLIED", "policy", policy_id,
        proposal, now
    )
    db.commit()
    return jsonify({"applied": True, "policy_id": policy_id, "new_auto_approve_max_amount": new_val, "proposal": proposal})


@workflows_bp.route("/notifications", methods=["GET"])
@require_auth
def list_notifications():
    rows = get_db().execute(
        """
        SELECT * FROM notifications
        WHERE user_id = ?
        ORDER BY id DESC LIMIT 50
        """,
        (g.current_user["id"],),
    ).fetchall()
    return jsonify({"notifications": [dict(r) for r in rows]})


@workflows_bp.route("/notifications/<int:notif_id>/read", methods=["POST"])
@require_auth
def mark_notification_read(notif_id: int):
    db = get_db()
    db.execute(
        "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
        (notif_id, g.current_user["id"]),
    )
    db.commit()
    return jsonify({"ok": True})


@workflows_bp.route("/notifications/sweep", methods=["POST"])
@require_roles("admin", "manager", "approver", "hr")
def trigger_reminder_sweep():
    result = run_reminder_sweep(get_db())
    return jsonify(result)
