"""Authentication, isolated admin login gateway, requester sign-up, and RBAC routes."""

from flask import Blueprint, g, jsonify, request

from .db import append_audit_log, get_db, utcnow_iso
from .security import (
    ROLE_CAPABILITIES,
    VALID_ROLES,
    create_token,
    hash_password,
    login_rate_limiter,
    require_auth,
    require_roles,
    validate_password_strength,
    verify_password,
)

auth_bp = Blueprint("auth", __name__, url_prefix="/api")

STANDARD_PORTAL_ROLES = ("requester", "manager", "approver", "hr")


def _client_rate_key(scope: str, username: str) -> str:
    ip = request.remote_addr or "unknown"
    return f"{scope}:{ip}:{username.lower()}"


def _user_payload(user) -> dict:
    return {
        "id": user["id"],
        "username": user["username"],
        "full_name": user["full_name"],
        "email": user["email"],
        "role": user["role"],
        "department": user["department"],
        "status": user["status"] if "status" in user.keys() else "active",
        "requested_role": user["requested_role"] if "requested_role" in user.keys() else user["role"],
        "capabilities": ROLE_CAPABILITIES.get(user["role"], []),
    }


@auth_bp.route("/auth/login", methods=["POST"])
def login():
    """Standard & role-specific staff login gateway (explicitly blocks admin accounts)."""
    data = request.get_json(silent=True) or {}
    identifier = (data.get("email") or data.get("username") or "").strip()
    password = data.get("password") or ""
    portal = (data.get("portal") or "staff").strip().lower()

    if not identifier and not password:
        return jsonify({"error": "Username and password are required"}), 400
    if not identifier:
        return jsonify({"error": "Username is required"}), 400
    if not password:
        return jsonify({"error": "Password is required"}), 400
    if portal not in ("staff", *STANDARD_PORTAL_ROLES):
        return jsonify({"error": "Invalid login portal"}), 400

    rate_key = _client_rate_key("standard", identifier)
    if login_rate_limiter.is_blocked(rate_key):
        return jsonify({"error": "Too many failed sign-in attempts. Please wait 5 minutes."}), 429

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE lower(username) = lower(?) OR lower(email) = lower(?)",
        (identifier, identifier),
    ).fetchone()
    if user and user["role"] == "admin":
        login_rate_limiter.record_failure(rate_key)
        append_audit_log(
            db, user["id"], user["username"], "BLOCKED_ADMIN_STANDARD_LOGIN", "auth", user["id"],
            {"portal": portal, "ip": request.remote_addr or "unknown"},
        )
        db.commit()
        return jsonify({"error": "Administrator sign-in is disabled on this gateway. Use the dedicated /login/admin portal."}), 403

    if user and not user["is_active"]:
        login_rate_limiter.record_failure(rate_key)
        u_status = user["status"] if "status" in user.keys() else "deactivated"
        if u_status == "pending_approval":
            return jsonify({"error": "Your corporate access request is currently pending Administrator review. You will be able to sign in once an administrator approves your access."}), 403
        if u_status == "rejected":
            reason = user["rejection_reason"] if "rejection_reason" in user.keys() and user["rejection_reason"] else "Not approved by administrator."
            return jsonify({"error": f"Your access request was rejected: {reason}"}), 403
        return jsonify({"error": "This account is deactivated. Please contact your administrator."}), 403

    if not user or not verify_password(password, user["password_hash"]):
        login_rate_limiter.record_failure(rate_key)
        return jsonify({"error": "Invalid credentials"}), 401

    if portal in STANDARD_PORTAL_ROLES and user["role"] != portal:
        login_rate_limiter.record_failure(rate_key)
        return jsonify({"error": f"This portal is restricted to '{portal}' accounts."}), 403

    login_rate_limiter.clear(rate_key)
    token = create_token(user["id"], user["username"], user["role"])
    append_audit_log(db, user["id"], user["username"], "USER_LOGIN", "user", user["id"], {"role": user["role"], "portal": portal})
    db.commit()
    return jsonify({"token": token, "user": _user_payload(user)})


@auth_bp.route("/auth/admin/login", methods=["POST"])
def admin_login():
    """Isolated administrator security gateway (only accessible to admin accounts)."""
    data = request.get_json(silent=True) or {}
    identifier = (data.get("email") or data.get("username") or "").strip()
    password = data.get("password") or ""
    if not identifier and not password:
        return jsonify({"error": "Administrator username and password are required"}), 400
    if not identifier:
        return jsonify({"error": "Administrator username is required"}), 400
    if not password:
        return jsonify({"error": "Administrator password is required"}), 400

    rate_key = _client_rate_key("admin", identifier)
    if login_rate_limiter.is_blocked(rate_key):
        return jsonify({"error": "Admin gateway temporarily locked due to failed attempts. Wait 5 minutes."}), 429

    db = get_db()
    user = db.execute(
        "SELECT * FROM users WHERE lower(username) = lower(?) OR lower(email) = lower(?)",
        (identifier, identifier),
    ).fetchone()
    if user and not user["is_active"]:
        login_rate_limiter.record_failure(rate_key)
        return jsonify({"error": "This administrator account is deactivated."}), 403

    if not user or not verify_password(password, user["password_hash"]):
        login_rate_limiter.record_failure(rate_key)
        append_audit_log(
            db, None, identifier or "unknown", "ADMIN_LOGIN_FAILED", "auth", None,
            {"ip": request.remote_addr or "unknown"},
        )
        db.commit()
        return jsonify({"error": "Invalid administrator credentials"}), 401

    if user["role"] != "admin":
        login_rate_limiter.record_failure(rate_key)
        append_audit_log(
            db, user["id"], user["username"], "ADMIN_GATEWAY_REJECTED", "auth", user["id"],
            {"actual_role": user["role"], "ip": request.remote_addr or "unknown"},
        )
        db.commit()
        return jsonify({"error": "Access denied: administrator privileges required for this gateway"}), 403

    login_rate_limiter.clear(rate_key)
    token = create_token(user["id"], user["username"], user["role"])
    append_audit_log(
        db, user["id"], user["username"], "ADMIN_LOGIN", "user", user["id"],
        {"ip": request.remote_addr or "unknown"},
    )
    db.commit()
    return jsonify({"token": token, "user": _user_payload(user)})


@auth_bp.route("/auth/register", methods=["POST"])
@auth_bp.route("/auth/request-access", methods=["POST"])
def register_requester():
    """Submit a corporate user access request for administrator review and approval."""
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip().lower()
    department = (data.get("department") or "General").strip()
    requested_role = (data.get("role") or data.get("requested_role") or "requester").strip().lower()
    if requested_role not in ("requester", "manager", "approver", "hr"):
        requested_role = "requester"

    if not username or not password or not full_name or not email:
        return jsonify({"error": "username, password, full_name, and email are required"}), 400
    pwd_err = validate_password_strength(password)
    if pwd_err:
        return jsonify({"error": pwd_err}), 400

    db = get_db()
    if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify({"error": "Username already exists"}), 409
    if db.execute("SELECT id FROM users WHERE lower(email) = ?", (email,)).fetchone():
        return jsonify({"error": "Corporate email already exists"}), 409

    now = utcnow_iso()
    cur = db.execute(
        """
        INSERT INTO users (username, password_hash, full_name, email, role, department, is_active, status, requested_role, created_at)
        VALUES (?, ?, ?, ?, 'requester', ?, 0, 'pending_approval', ?, ?)
        """,
        (username, hash_password(password), full_name, email, department, requested_role, now),
    )
    uid = cur.lastrowid
    append_audit_log(
        db, uid, username, "USER_ACCESS_REQUESTED", "user", uid,
        {"department": department, "requested_role": requested_role, "email": email}, now,
    )
    # Alert administrators about pending user access request
    admins = db.execute("SELECT id FROM users WHERE role = 'admin' AND is_active = 1").fetchall()
    for adm in admins:
        db.execute(
            """
            INSERT INTO notifications (user_id, request_id, category, title, message, is_read, created_at)
            VALUES (?, NULL, 'access_request', 'New User Access Request', ?, 0, ?)
            """,
            (
                adm["id"],
                f"User {full_name} (@{username}, {email}) requested {requested_role.title()} access for {department}.",
                now,
            ),
        )
    db.commit()
    user = db.execute("SELECT * FROM users WHERE id = ?", (uid,)).fetchone()
    return jsonify({
        "message": "Your corporate access request has been submitted to the Administrator for approval. You will receive an email once your account is active.",
        "status": "pending_approval",
        "user": _user_payload(user),
    }), 201


@auth_bp.route("/admin/access-requests", methods=["GET"])
@require_roles("admin", "hr")
def list_access_requests():
    """List pending user access requests awaiting administrator review."""
    db = get_db()
    rows = db.execute(
        """
        SELECT id, username, full_name, email, role, department, status, requested_role, created_at
        FROM users
        WHERE status = 'pending_approval' OR (is_active = 0 AND status != 'rejected' AND role != 'admin')
        ORDER BY id DESC
        """
    ).fetchall()
    return jsonify({"requests": [dict(r) for r in rows]})


@auth_bp.route("/admin/access-requests/<int:user_id>/decision", methods=["POST"])
@require_roles("admin", "hr")
def decide_access_request(user_id: int):
    """Approve or reject a user access request."""
    data = request.get_json(silent=True) or {}
    decision = (data.get("decision") or "").strip().lower()
    if decision not in ("approve", "reject"):
        return jsonify({"error": "decision must be 'approve' or 'reject'"}), 400

    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        return jsonify({"error": "User access request not found"}), 404

    now = utcnow_iso()
    admin_id = g.current_user["id"]
    admin_uname = g.current_user["username"]

    if decision == "approve":
        assigned_role = (data.get("role") or target["requested_role"] or "requester").strip().lower()
        if assigned_role not in VALID_ROLES:
            assigned_role = "requester"
        if g.current_user["role"] == "hr" and assigned_role == "admin":
            return jsonify({"error": "HR cannot grant administrator access"}), 403

        assigned_dept = (data.get("department") or target["department"] or "General").strip()
        db.execute(
            """
            UPDATE users
            SET is_active = 1, status = 'active', role = ?, department = ?, reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (assigned_role, assigned_dept, admin_id, now, user_id),
        )
        append_audit_log(
            db, admin_id, admin_uname, "USER_ACCESS_APPROVED", "user", user_id,
            {"assigned_role": assigned_role, "department": assigned_dept, "target_username": target["username"]},
            now,
        )
        db.execute(
            """
            INSERT INTO notifications (user_id, request_id, category, title, message, is_read, created_at)
            VALUES (?, NULL, 'access_granted', 'System Access Approved', ?, 0, ?)
            """,
            (
                user_id,
                f"Your access request has been approved! You have been granted '{assigned_role.title()}' access for {assigned_dept}.",
                now,
            ),
        )
        db.commit()
        return jsonify({
            "message": f"Access granted for @{target['username']} with role '{assigned_role}'.",
            "user_id": user_id,
            "status": "active",
            "role": assigned_role,
        })
    else:
        reason = (data.get("rejection_reason") or "Access request declined by administrator.").strip()
        db.execute(
            """
            UPDATE users
            SET is_active = 0, status = 'rejected', rejection_reason = ?, reviewed_by = ?, reviewed_at = ?
            WHERE id = ?
            """,
            (reason, admin_id, now, user_id),
        )
        append_audit_log(
            db, admin_id, admin_uname, "USER_ACCESS_REJECTED", "user", user_id,
            {"reason": reason, "target_username": target["username"]},
            now,
        )
        db.commit()
        return jsonify({
            "message": f"Access request for @{target['username']} has been rejected.",
            "user_id": user_id,
            "status": "rejected",
        })


@auth_bp.route("/auth/me", methods=["GET"])
@require_auth
def me():
    db = get_db()
    user = dict(g.current_user)
    user["capabilities"] = ROLE_CAPABILITIES.get(user["role"], [])
    stats = db.execute(
        """
        SELECT COUNT(*) AS total_submitted,
               COALESCE(SUM(CASE WHEN status IN ('pending', 'in_review', 'flagged') THEN 1 ELSE 0 END), 0) AS pending_count,
               COALESCE(SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END), 0) AS approved_count,
               COALESCE(SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END), 0) AS rejected_count,
               COALESCE(SUM(amount), 0) AS total_amount_spent
        FROM requests WHERE requester_id = ?
        """,
        (user["id"],),
    ).fetchone()
    user["stats"] = dict(stats) if stats else {}
    return jsonify({"user": user})


@auth_bp.route("/auth/profile", methods=["PATCH"])
@require_auth
def update_own_profile():
    """Allow logged in users to update their own full name, email, or change password."""
    data = request.get_json(silent=True) or {}
    db = get_db()
    user_id = g.current_user["id"]
    current_user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not current_user:
        return jsonify({"error": "User not found"}), 404

    full_name = (data.get("full_name") or current_user["full_name"]).strip()
    email = (data.get("email") or current_user["email"]).strip().lower()

    if not full_name or not email:
        return jsonify({"error": "full_name and email cannot be empty"}), 400

    new_password = (data.get("new_password") or "").strip()
    if new_password:
        current_password = data.get("current_password") or ""
        if not verify_password(current_password, current_user["password_hash"]):
            return jsonify({"error": "Current password is incorrect"}), 403
        pwd_err = validate_password_strength(new_password)
        if pwd_err:
            return jsonify({"error": pwd_err}), 400
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )

    db.execute(
        "UPDATE users SET full_name = ?, email = ? WHERE id = ?",
        (full_name, email, user_id),
    )
    now = utcnow_iso()
    append_audit_log(
        db, user_id, current_user["username"], "PROFILE_UPDATED", "user", user_id,
        {"full_name": full_name, "email": email, "password_changed": bool(new_password)},
        now,
    )
    db.commit()
    updated = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return jsonify({"user": _user_payload(updated), "message": "Profile updated successfully"})


@auth_bp.route("/users", methods=["GET"])
@require_roles("admin", "hr")
def list_users():
    db = get_db()
    rows = db.execute(
        "SELECT id, username, full_name, email, role, department, status, requested_role, is_active, created_at FROM users ORDER BY id ASC"
    ).fetchall()
    return jsonify({"users": [dict(r) for r in rows]})


@auth_bp.route("/users", methods=["POST"])
@require_roles("admin", "hr")
def create_user():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    full_name = (data.get("full_name") or "").strip()
    email = (data.get("email") or "").strip()
    role = (data.get("role") or "requester").strip().lower()
    department = (data.get("department") or "General").strip()

    if not username or not password or not full_name or not email:
        return jsonify({"error": "username, password, full_name, and email are required"}), 400
    if role not in VALID_ROLES:
        return jsonify({"error": f"Invalid role. Must be one of {VALID_ROLES}"}), 400
    if g.current_user["role"] == "hr" and role == "admin":
        return jsonify({"error": "HR cannot create admin users"}), 403

    db = get_db()
    if db.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone():
        return jsonify({"error": "Username already exists"}), 409

    now = utcnow_iso()
    cur = db.execute(
        """
        INSERT INTO users (username, password_hash, full_name, email, role, department, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, ?, 1, ?)
        """,
        (username, hash_password(password), full_name, email, role, department, now),
    )
    uid = cur.lastrowid
    append_audit_log(
        db, g.current_user["id"], g.current_user["username"], "USER_CREATED", "user", uid,
        {"username": username, "role": role, "department": department}, now
    )
    db.commit()
    return jsonify({"id": uid, "username": username, "role": role}), 201


@auth_bp.route("/users/<int:user_id>", methods=["PATCH"])
@require_roles("admin", "hr")
def update_user(user_id: int):
    data = request.get_json(silent=True) or {}
    db = get_db()
    target = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    if not target:
        return jsonify({"error": "User not found"}), 404

    new_role = data.get("role", target["role"])
    if new_role not in VALID_ROLES:
        return jsonify({"error": f"Invalid role. Must be one of {VALID_ROLES}"}), 400
    if g.current_user["role"] == "hr" and (target["role"] == "admin" or new_role == "admin"):
        return jsonify({"error": "HR cannot modify admin accounts"}), 403

    full_name = data.get("full_name", target["full_name"])
    email = data.get("email", target["email"])
    department = data.get("department", target["department"])
    is_active = 1 if data.get("is_active", target["is_active"]) else 0

    # Optional password reset (admin only)
    new_password = (data.get("password") or "").strip()
    if new_password:
        if g.current_user["role"] != "admin":
            return jsonify({"error": "Only administrators can reset passwords"}), 403
        pwd_err = validate_password_strength(new_password)
        if pwd_err:
            return jsonify({"error": pwd_err}), 400
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (hash_password(new_password), user_id),
        )
        append_audit_log(
            db, g.current_user["id"], g.current_user["username"], "USER_PASSWORD_RESET", "user", user_id, {}
        )

    db.execute(
        "UPDATE users SET full_name = ?, email = ?, role = ?, department = ?, is_active = ? WHERE id = ?",
        (full_name, email, new_role, department, is_active, user_id),
    )
    append_audit_log(
        db, g.current_user["id"], g.current_user["username"], "USER_UPDATED", "user", user_id,
        {"role": new_role, "department": department, "is_active": is_active}
    )
    db.commit()
    return jsonify({"id": user_id, "role": new_role, "is_active": bool(is_active)})
