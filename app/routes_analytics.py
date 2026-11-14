"""Reporting, analytics, predictions, optimization, audit trail, and health monitoring routes."""

import csv
import hashlib
import io
from flask import Blueprint, Response, g, jsonify, request

from .ai_engine import ai_engine, analyze_workflows_and_rules, predict_bottlenecks_and_forecast
from .db import get_db
from .security import require_auth, require_roles
from .storage import get_storage_config

analytics_bp = Blueprint("analytics", __name__, url_prefix="/api")


@analytics_bp.route("/health", methods=["GET"])
def health():
    db = get_db()
    req_count = db.execute("SELECT COUNT(*) AS c FROM requests").fetchone()["c"]
    storage_cfg = get_storage_config(db)
    return jsonify({
        "status": "ok",
        "database": "sqlite_wal",
        "storage_backend": storage_cfg["backend"],
        "ai_model_trained": ai_engine.is_trained,
        "total_requests": req_count,
    })


@analytics_bp.route("/analytics/dashboard", methods=["GET"])
@require_auth
def dashboard_metrics():
    db = get_db()
    summary = db.execute(
        """
        SELECT
            COUNT(*) AS total_requests,
            COALESCE(SUM(CASE WHEN status IN ('pending', 'in_review', 'flagged') THEN 1 ELSE 0 END), 0) AS active_requests,
            COALESCE(SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END), 0) AS approved_requests,
            COALESCE(SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END), 0) AS rejected_requests,
            COALESCE(SUM(CASE WHEN status = 'flagged' OR is_anomaly = 1 THEN 1 ELSE 0 END), 0) AS anomaly_requests,
            COALESCE(SUM(CASE WHEN auto_approved = 1 THEN 1 ELSE 0 END), 0) AS auto_approved_requests,
            COALESCE(SUM(amount), 0) AS total_amount
        FROM requests
        """
    ).fetchone()

    avg_cycle = db.execute(
        "SELECT COALESCE(AVG(cycle_time_hours), 0) AS avg_h FROM approvals"
    ).fetchone()["avg_h"]

    by_type = [
        dict(r)
        for r in db.execute(
            """
            SELECT request_type, COUNT(*) AS count, COALESCE(SUM(amount), 0) AS total_amount,
                   SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) AS approved_count
            FROM requests
            GROUP BY request_type
            """
        ).fetchall()
    ]

    by_status = [
        dict(r)
        for r in db.execute(
            "SELECT status, COUNT(*) AS count FROM requests GROUP BY status"
        ).fetchall()
    ]

    total = summary["total_requests"] or 0
    approved = summary["approved_requests"] or 0
    auto_app = summary["auto_approved_requests"] or 0

    return jsonify({
        "summary": {
            **dict(summary),
            "approval_rate_pct": round((approved / total) * 100, 1) if total else 0.0,
            "auto_approval_rate_pct": round((auto_app / total) * 100, 1) if total else 0.0,
            "avg_cycle_time_hours": round(float(avg_cycle), 2),
        },
        "by_type": by_type,
        "by_status": by_status,
    })


@analytics_bp.route("/analytics/predictions", methods=["GET"])
@require_roles("manager", "approver", "hr", "admin")
def predictions():
    return jsonify(predict_bottlenecks_and_forecast(get_db()))


@analytics_bp.route("/analytics/optimizations", methods=["GET"])
@require_roles("manager", "approver", "hr", "admin")
def optimizations():
    return jsonify(analyze_workflows_and_rules(get_db()))


@analytics_bp.route("/analytics/export.csv", methods=["GET"])
@require_roles("manager", "approver", "hr", "admin")
def export_csv():
    """Export filtered accounting and reconciliation records in CSV format."""
    db = get_db()
    status_filter = request.args.get("status")
    department_filter = request.args.get("department")
    type_filter = request.args.get("request_type")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = """
        SELECT r.id, u.username AS requester_username, u.full_name AS requester_name,
               r.department, r.request_type, r.title, r.amount, r.currency,
               COALESCE(r.amount_usd, r.amount) AS amount_usd,
               r.status, COALESCE(r.rejection_reason, '') AS rejection_reason,
               r.urgency, r.ai_recommendation, r.ai_risk_score, r.is_anomaly,
               r.auto_approved, r.created_at, COALESCE(r.completed_at, '') AS completed_at
        FROM requests r
        JOIN users u ON u.id = r.requester_id
        WHERE (r.is_draft = 0 OR r.is_draft IS NULL)
    """
    params = []

    if status_filter:
        query += " AND r.status = ?"
        params.append(status_filter)
    if department_filter:
        query += " AND r.department = ?"
        params.append(department_filter)
    if type_filter:
        query += " AND r.request_type = ?"
        params.append(type_filter)
    if start_date:
        query += " AND date(r.created_at) >= date(?)"
        params.append(start_date)
    if end_date:
        query += " AND date(r.created_at) <= date(?)"
        params.append(end_date)

    query += " ORDER BY r.id DESC"
    rows = db.execute(query, params).fetchall()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "Request ID", "Requester Username", "Requester Name", "Department",
        "Category", "Title", "Amount", "Currency", "Amount (USD)",
        "Status", "Rejection / Cancellation Reason", "Urgency",
        "AI Recommendation", "AI Risk Score", "Anomaly Flag",
        "Auto-Approved", "Created At", "Completed At",
    ])
    for r in rows:
        writer.writerow(list(r))

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=approval_accounting_report.csv"},
    )


@analytics_bp.route("/audit", methods=["GET"])
@require_roles("admin")
def list_audit_logs():
    rows = get_db().execute("SELECT * FROM audit_logs ORDER BY id DESC LIMIT 100").fetchall()
    return jsonify({"audit_logs": [dict(r) for r in rows]})


@analytics_bp.route("/audit/verify", methods=["GET"])
@require_roles("admin")
def verify_audit_chain():
    """Verify SHA-256 hash chain integrity of audit_logs (FR-14)."""
    rows = get_db().execute("SELECT * FROM audit_logs ORDER BY id ASC").fetchall()
    if not rows:
        return jsonify({"valid": True, "entries_verified": 0, "genesis_intact": True})
    prev = rows[0]["prev_hash"]
    for r in rows:
        raw = f"{prev}|{r['created_at']}|{r['actor_id']}|{r['actor_username']}|{r['action']}|{r['entity_type']}|{r['entity_id']}|{r['details_json']}"
        expected = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        if r["prev_hash"] != prev or r["entry_hash"] != expected:
            return jsonify({"valid": False, "broken_at_id": r["id"]}), 200
        prev = r["entry_hash"]
    return jsonify({"valid": True, "entries_verified": len(rows), "genesis_intact": rows[0]["prev_hash"] == "GENESIS"})


@analytics_bp.route("/analytics/role-dashboard", methods=["GET"])
@require_auth
def role_dashboard():
    """Return lightweight role-specific dashboard summary & queue items."""
    db = get_db()
    user = g.current_user
    role = user["role"]

    if role == "requester":
        stats = dict(
            db.execute(
                """
                SELECT COUNT(*) AS my_total,
                       COALESCE(SUM(CASE WHEN status IN ('pending', 'in_review', 'flagged') THEN 1 ELSE 0 END), 0) AS my_active,
                       COALESCE(SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END), 0) AS my_approved,
                       COALESCE(SUM(CASE WHEN auto_approved = 1 THEN 1 ELSE 0 END), 0) AS my_auto_approved
                FROM requests WHERE requester_id = ?
                """,
                (user["id"],),
            ).fetchone()
        )
        recent = [
            dict(r)
            for r in db.execute(
                "SELECT id, title, request_type, amount, currency, status, auto_approved, created_at FROM requests WHERE requester_id = ? ORDER BY id DESC LIMIT 8",
                (user["id"],),
            ).fetchall()
        ]
        return jsonify({"role": role, "stats": stats, "items": recent})

    if role in ("manager", "approver", "hr"):
        queue = [
            dict(r)
            for r in db.execute(
                """
                SELECT r.id, r.title, r.request_type, r.amount, r.currency, r.status,
                       r.ai_recommendation, r.ai_risk_score, r.is_anomaly, t.stage_name, t.due_at,
                       u.full_name AS requester_name
                FROM approval_tasks t
                JOIN requests r ON r.id = t.request_id
                JOIN users u ON u.id = r.requester_id
                WHERE t.status = 'pending' AND t.assigned_role = ?
                ORDER BY r.is_anomaly DESC, r.id DESC LIMIT 15
                """,
                (role,),
            ).fetchall()
        ]
        flagged = [
            dict(r)
            for r in db.execute(
                "SELECT id, title, request_type, amount, currency, ai_risk_score, created_at FROM requests WHERE is_anomaly = 1 AND status IN ('flagged', 'in_review') ORDER BY id DESC LIMIT 10"
            ).fetchall()
        ]
        extra = {}
        if role == "hr":
            extra["leave_count"] = db.execute(
                "SELECT COUNT(*) AS c FROM requests WHERE request_type = 'leave_request'"
            ).fetchone()["c"]
            extra["user_count"] = db.execute("SELECT COUNT(*) AS c FROM users WHERE is_active = 1").fetchone()["c"]
        return jsonify({"role": role, "queue": queue, "flagged": flagged, "extra": extra})

    # admin
    storage_cfg = get_storage_config(db)
    return jsonify({
        "role": "admin",
        "system": {
            "database": "SQLite (WAL Mode)",
            "storage_backend": storage_cfg["backend"],
            "ai_cached_samples": ai_engine._last_trained_count,
            "ai_trained": ai_engine.is_trained,
        },
    })


@analytics_bp.route("/ai/retrain", methods=["POST"])
@require_roles("admin")
def retrain_ai_models():
    res = ai_engine.train_from_db(get_db(), force=True)
    return jsonify(res)
