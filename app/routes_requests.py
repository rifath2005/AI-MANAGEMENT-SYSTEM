"""Request submission, file attachments, tracking, approval actions, and NLP/chat routes."""

import hashlib
import json
from flask import Blueprint, Response, current_app, g, jsonify, request

from .ai_engine import extract_nlp_metadata
from .chat_llm import (
    generate_finetune_dataset,
    interpret_chat_with_project_llm,
    mask_api_key,
    resolve_llm_config,
)
from .db import append_audit_log, get_db, utcnow_iso
from .security import require_auth, require_roles
from .storage import fetch_attachment_bytes, get_storage_config, save_attachment_bytes
from .workflow_engine import process_approval_decision, submit_and_route_request

requests_bp = Blueprint("requests", __name__, url_prefix="/api")


def _allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in current_app.config["ALLOWED_EXTENSIONS"]


def _serialize_request(row) -> dict:
    d = dict(row)
    d["anomaly_reasons"] = json.loads(d.pop("anomaly_reasons_json", "[]") or "[]")
    d["nlp_extracted"] = json.loads(d.pop("nlp_extracted_json", "{}") or "{}")
    d["is_anomaly"] = bool(d.get("is_anomaly"))
    d["auto_approved"] = bool(d.get("auto_approved"))
    return d


@requests_bp.route("/requests", methods=["GET"])
@require_auth
def list_requests():
    db = get_db()
    user = g.current_user
    role = user["role"]
    status_filter = request.args.get("status")
    scope = request.args.get("scope")  # 'mine' | 'queue' | 'all'

    query = """
        SELECT r.*, u.username AS requester_username, u.full_name AS requester_name
        FROM requests r
        JOIN users u ON u.id = r.requester_id
        WHERE 1=1
    """
    params = []

    if scope == "mine" or role == "requester":
        query += " AND r.requester_id = ?"
        params.append(user["id"])
    elif scope == "queue":
        query += """
            AND EXISTS (
                SELECT 1 FROM approval_tasks t
                WHERE t.request_id = r.id AND t.status = 'pending' AND t.assigned_role = ?
            )
        """
        params.append(role)
    elif role == "hr":
        query += " AND (r.request_type = 'leave_request' OR r.requester_id = ?)"
        params.append(user["id"])
    elif role in ("manager", "approver"):
        query += """
            AND (
                r.requester_id = ?
                OR EXISTS (SELECT 1 FROM approval_tasks t WHERE t.request_id = r.id AND t.assigned_role = ?)
            )
        """
        params.extend([user["id"], role])

    if status_filter:
        query += " AND r.status = ?"
        params.append(status_filter)

    query += " ORDER BY r.id DESC LIMIT 200"
    rows = db.execute(query, params).fetchall()
    return jsonify({"requests": [_serialize_request(r) for r in rows]})


@requests_bp.route("/requests/<int:request_id>", methods=["GET"])
@require_auth
def get_request_detail(request_id: int):
    db = get_db()
    row = db.execute(
        """
        SELECT r.*, u.username AS requester_username, u.full_name AS requester_name
        FROM requests r
        JOIN users u ON u.id = r.requester_id
        WHERE r.id = ?
        """,
        (request_id,),
    ).fetchone()
    if not row:
        return jsonify({"error": "Request not found"}), 404

    user = g.current_user
    if user["role"] == "requester" and row["requester_id"] != user["id"]:
        return jsonify({"error": "Access denied"}), 403

    tasks = [
        dict(t)
        for t in db.execute(
            """
            SELECT t.*, u.full_name AS decision_by_name
            FROM approval_tasks t
            LEFT JOIN users u ON u.id = t.decision_by
            WHERE t.request_id = ?
            ORDER BY t.stage_index ASC
            """,
            (request_id,),
        ).fetchall()
    ]
    approvals = [
        dict(a)
        for a in db.execute(
            """
            SELECT a.*, u.full_name AS approver_name, u.role AS approver_role
            FROM approvals a
            JOIN users u ON u.id = a.approver_id
            WHERE a.request_id = ?
            ORDER BY a.id ASC
            """,
            (request_id,),
        ).fetchall()
    ]
    attachments = [
        dict(f)
        for f in db.execute(
            "SELECT id, original_filename, storage_backend, content_type, size_bytes, sha256_hash, created_at FROM request_attachments WHERE request_id = ?",
            (request_id,),
        ).fetchall()
    ]

    return jsonify({
        "request": _serialize_request(row),
        "tasks": tasks,
        "approvals": approvals,
        "attachments": attachments,
    })


@requests_bp.route("/requests", methods=["POST"])
@require_auth
def create_request():
    db = get_db()
    user = g.current_user

    if request.content_type and "multipart/form-data" in request.content_type:
        payload = {
            "request_type": request.form.get("request_type"),
            "title": request.form.get("title", ""),
            "description": request.form.get("description", ""),
            "amount": request.form.get("amount"),
            "currency": request.form.get("currency", "USD"),
            "department": request.form.get("department", user["department"]),
            "urgency": request.form.get("urgency", "normal"),
        }
        uploaded_file = request.files.get("attachment")
    else:
        payload = request.get_json(silent=True) or {}
        uploaded_file = None

    title = (payload.get("title") or "").strip()
    description = (payload.get("description") or "").strip()
    if not title or not description:
        return jsonify({"error": "title and description are required"}), 400

    # Fill missing fields via NLP extraction if omitted
    nlp_meta = extract_nlp_metadata(description)
    if not payload.get("request_type"):
        payload["request_type"] = nlp_meta["request_type"]
    if payload.get("amount") in (None, ""):
        payload["amount"] = nlp_meta["amount"]
    if not payload.get("urgency"):
        payload["urgency"] = nlp_meta["urgency"]

    has_attachment = bool(uploaded_file and uploaded_file.filename)
    if has_attachment and not _allowed_file(uploaded_file.filename):
        return jsonify({"error": "Unsupported attachment file type"}), 400

    result = submit_and_route_request(db, user, payload, has_attachment=has_attachment)
    req_id = result["request_id"]

    if has_attachment:
        file_bytes = uploaded_file.read()
        stored = save_attachment_bytes(db, req_id, uploaded_file.filename, file_bytes, uploaded_file.mimetype)
        sha256 = hashlib.sha256(file_bytes).hexdigest()
        db.execute(
            """
            INSERT INTO request_attachments (request_id, original_filename, stored_filename, storage_backend, content_type, size_bytes, sha256_hash, uploaded_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (req_id, stored["original_filename"], stored["stored_filename"], stored["backend"], uploaded_file.mimetype, len(file_bytes), sha256, user["id"], utcnow_iso()),
        )
        append_audit_log(
            db, user["id"], user["username"], "ATTACHMENT_UPLOADED", "request", req_id,
            {"filename": stored["original_filename"], "size_bytes": len(file_bytes), "backend": stored["backend"]}
        )
        db.commit()

    return jsonify(result), 201


@requests_bp.route("/requests/<int:request_id>/attachments/<int:attachment_id>", methods=["GET"])
@require_auth
def download_attachment(request_id: int, attachment_id: int):
    db = get_db()
    att = db.execute(
        "SELECT * FROM request_attachments WHERE id = ? AND request_id = ?",
        (attachment_id, request_id),
    ).fetchone()
    if not att:
        return jsonify({"error": "Attachment not found"}), 404
    backend = att["storage_backend"] if "storage_backend" in att.keys() else "local"
    content = fetch_attachment_bytes(db, att["stored_filename"], backend=backend)
    if content is None:
        return jsonify({"error": "Attachment file missing from storage"}), 404
    return Response(
        content,
        mimetype=att["content_type"] or "application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={att['original_filename']}"},
    )


@requests_bp.route("/storage/config", methods=["GET"])
@require_auth
def get_storage_status():
    cfg = get_storage_config(get_db())
    return jsonify({
        "backend": cfg["backend"],
        "supabase_configured": cfg["supabase_configured"],
        "supabase_url": cfg["supabase_url"],
        "bucket": cfg["bucket"],
        "masked_key": cfg["masked_key"],
    })


@requests_bp.route("/storage/config", methods=["POST"])
@require_roles("admin")
def save_storage_config():
    data = request.get_json(silent=True) or {}
    db = get_db()
    now = utcnow_iso()
    updates = {
        "supabase_url": (data.get("supabase_url") or "").strip().rstrip("/"),
        "supabase_key": (data.get("supabase_key") or "").strip(),
        "supabase_bucket": (data.get("bucket") or "approval-attachments").strip(),
    }
    for k, v in updates.items():
        db.execute(
            """
            INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (k, v, now),
        )
    append_audit_log(
        db, g.current_user["id"], g.current_user["username"], "STORAGE_CONFIG_UPDATED", "settings", None,
        {"supabase_url": updates["supabase_url"], "bucket": updates["supabase_bucket"], "key_set": bool(updates["supabase_key"])}, now
    )
    db.commit()
    cfg = get_storage_config(db)
    return jsonify({
        "backend": cfg["backend"],
        "supabase_configured": cfg["supabase_configured"],
        "supabase_url": cfg["supabase_url"],
        "bucket": cfg["bucket"],
        "masked_key": cfg["masked_key"],
    })


@requests_bp.route("/requests/<int:request_id>/decision", methods=["POST"])
@require_roles("manager", "approver", "hr", "admin")
def decide_request(request_id: int):
    data = request.get_json(silent=True) or {}
    decision = (data.get("decision") or "").strip().lower()
    comment = (data.get("comment") or "").strip()
    res, code = process_approval_decision(get_db(), g.current_user, request_id, decision, comment)
    return jsonify(res), code


@requests_bp.route("/nlp/analyze", methods=["POST"])
@require_auth
def analyze_nlp_text():
    data = request.get_json(silent=True) or {}
    text = data.get("text") or ""
    if not text.strip():
        return jsonify({"error": "text is required"}), 400
    return jsonify({"extracted": extract_nlp_metadata(text)})


@requests_bp.route("/chat/config", methods=["GET"])
@require_auth
def get_chat_config():
    cfg = resolve_llm_config(
        get_db(),
        header_key=request.headers.get("X-LLM-API-Key", ""),
        header_provider=request.headers.get("X-LLM-Provider", ""),
        header_model=request.headers.get("X-LLM-Model", ""),
        header_base_url=request.headers.get("X-LLM-Base-Url", ""),
    )
    return jsonify({
        "configured": cfg["configured"],
        "provider": cfg["provider"],
        "model": cfg["model"],
        "masked_key": mask_api_key(cfg["api_key"]),
        "base_url": cfg["base_url"],
    })


@requests_bp.route("/chat/config", methods=["POST"])
@require_roles("admin")
def save_chat_config():
    """Persist global chat LLM API key/provider/model in app_settings (admin only)."""
    data = request.get_json(silent=True) or {}
    db = get_db()
    now = utcnow_iso()
    updates = {
        "llm_api_key": (data.get("api_key") or "").strip(),
        "llm_provider": (data.get("provider") or "auto").strip().lower(),
        "llm_model": (data.get("model") or "").strip(),
        "llm_base_url": (data.get("base_url") or "").strip(),
    }
    for k, v in updates.items():
        db.execute(
            """
            INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (k, v, now),
        )
    append_audit_log(
        db, g.current_user["id"], g.current_user["username"], "CHAT_LLM_CONFIG_UPDATED", "settings", None,
        {"provider": updates["llm_provider"], "model": updates["llm_model"], "key_set": bool(updates["llm_api_key"])}, now
    )
    db.commit()
    cfg = resolve_llm_config(db)
    return jsonify({
        "configured": cfg["configured"],
        "provider": cfg["provider"],
        "model": cfg["model"],
        "masked_key": mask_api_key(cfg["api_key"]),
    })


@requests_bp.route("/chat/finetune-dataset", methods=["GET"])
@require_auth
def export_chat_finetune_dataset():
    """Download project-specific JSONL fine-tuning dataset for OpenAI or Gemini."""
    fmt = (request.args.get("format") or "openai").strip().lower()
    if fmt not in ("openai", "gemini"):
        return jsonify({"error": "format must be 'openai' or 'gemini'"}), 400
    records = generate_finetune_dataset(get_db(), fmt=fmt)
    jsonl = "\n".join(json.dumps(r) for r in records) + "\n"
    return Response(
        jsonl,
        mimetype="application/jsonl",
        headers={"Content-Disposition": f"attachment; filename=ams_chat_finetune_{fmt}.jsonl"},
    )


@requests_bp.route("/chat", methods=["POST"])
@require_auth
def chat_command():
    """Voice & chat NLP endpoint supporting BYOK project-tuned LLM or free local NLP fallback."""
    data = request.get_json(silent=True) or {}
    message = (data.get("message") or "").strip()
    if not message:
        return jsonify({"error": "message is required"}), 400

    db = get_db()
    user = g.current_user
    cfg = resolve_llm_config(
        db,
        header_key=request.headers.get("X-LLM-API-Key", "") or (data.get("api_key") or ""),
        header_provider=request.headers.get("X-LLM-Provider", "") or (data.get("provider") or ""),
        header_model=request.headers.get("X-LLM-Model", "") or (data.get("model") or ""),
        header_base_url=request.headers.get("X-LLM-Base-Url", "") or (data.get("base_url") or ""),
    )

    parsed = interpret_chat_with_project_llm(db, user, message, cfg)
    intent = parsed.get("intent", "help")
    engine = parsed.get("_engine", "local_nlp")

    if intent == "submit_request":
        if not parsed.get("title"):
            parsed["title"] = message[:65].strip()
        if not parsed.get("description"):
            parsed["description"] = message
        parsed.setdefault("request_type", "expense_report")
        parsed.setdefault("amount", 0.0)
        parsed.setdefault("currency", "USD")
        res = submit_and_route_request(db, user, parsed, has_attachment=False)
        return jsonify({
            "intent": intent,
            "engine": engine,
            "reply": f"Created Request #{res['request_id']} ({parsed['request_type']}, {parsed['amount']} {parsed['currency']}). Status: {res['status']}. {res['ai_evaluation']['explanation']}",
            "data": res,
        }), 201

    if intent == "check_status":
        req_id = int(parsed.get("request_id") or 0)
        row = db.execute("SELECT id, title, status, amount, requester_id FROM requests WHERE id = ?", (req_id,)).fetchone()
        if not row:
            return jsonify({"intent": intent, "engine": engine, "reply": f"Request #{req_id} was not found."}), 404
        if user["role"] == "requester" and row["requester_id"] != user["id"]:
            return jsonify({"intent": intent, "engine": engine, "reply": "You do not have access to view that request."}), 403
        return jsonify({
            "intent": intent,
            "engine": engine,
            "reply": f"Request #{row['id']} ('{row['title']}', amount {row['amount']}) is currently '{row['status']}'.",
            "data": dict(row),
        })

    if intent == "list_my_requests":
        rows = [
            dict(r)
            for r in db.execute(
                "SELECT id, title, request_type, amount, status FROM requests WHERE requester_id = ? ORDER BY id DESC LIMIT 5",
                (user["id"],),
            ).fetchall()
        ]
        summary = ", ".join([f"#{r['id']} {r['title']} ({r['status']})" for r in rows]) or "No requests found."
        return jsonify({"intent": intent, "engine": engine, "reply": f"Your recent requests: {summary}", "data": rows})

    if intent == "list_pending":
        rows = [
            dict(r)
            for r in db.execute(
                """
                SELECT r.id, r.title, r.amount, r.request_type
                FROM approval_tasks t
                JOIN requests r ON r.id = t.request_id
                WHERE t.status = 'pending' AND (t.assigned_role = ? OR ? = 'admin')
                ORDER BY r.id DESC LIMIT 10
                """,
                (user["role"], user["role"]),
            ).fetchall()
        ]
        summary = ", ".join([f"#{r['id']} {r['title']} (${r['amount']})" for r in rows]) or "No pending approvals in your queue."
        return jsonify({"intent": intent, "engine": engine, "reply": f"Pending queue for {user['role']}: {summary}", "data": rows})

    if intent in ("approve_request", "reject_request"):
        if user["role"] not in ("manager", "approver", "hr", "admin"):
            return jsonify({"intent": intent, "engine": engine, "reply": "Your role cannot approve or reject requests."}), 403
        req_id = int(parsed.get("request_id") or 0)
        comment = parsed.get("comment") or f"Processed via chat ({intent})"
        decision = "approved" if intent == "approve_request" else "rejected"
        res, code = process_approval_decision(db, user, req_id, decision, comment)
        reply = (
            f"Request #{req_id} marked {res.get('status')}."
            if code == 200
            else f"Could not process decision: {res.get('error')}"
        )
        return jsonify({"intent": intent, "engine": engine, "reply": reply, "data": res}), code

    if intent == "policy_qa":
        return jsonify({"intent": intent, "engine": engine, "reply": parsed.get("reply") or "Ask me about policies, workflows, or request status."})

    return jsonify({
        "intent": "help",
        "engine": engine,
        "reply": parsed.get("reply") or parsed.get("message") or "Try: 'Submit an expense report for $180 for team dinner', 'Check status of request 5', or 'What is the expense auto-approval limit?'",
    })
