"""Authentication, password hashing, signed tokens, and RBAC helpers."""

import base64
import hashlib
import hmac
import json
import os
import time
from functools import wraps
from flask import current_app, g, jsonify, request

VALID_ROLES = ("requester", "manager", "approver", "hr", "admin")

ROLE_CAPABILITIES = {
    "requester": ["submit_request", "view_own_requests", "chat_submit"],
    "manager": ["submit_request", "view_own_requests", "view_team_requests", "approve_request", "view_reports", "chat_submit"],
    "approver": ["submit_request", "view_own_requests", "view_assigned_approvals", "approve_request", "review_anomalies", "chat_submit"],
    "hr": ["submit_request", "view_own_requests", "view_leave_requests", "approve_request", "manage_users", "view_reports", "chat_submit"],
    "admin": [
        "submit_request", "view_all_requests", "approve_request", "review_anomalies",
        "manage_users", "manage_workflows", "manage_policies", "view_reports", "view_audit", "chat_submit",
    ],
}


def hash_password(password: str, salt: bytes | None = None) -> str:
    """Hash password with PBKDF2-HMAC-SHA256."""
    if salt is None:
        salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
    return f"{base64.b64encode(salt).decode()}${base64.b64encode(digest).decode()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Verify password against stored salted PBKDF2 hash."""
    try:
        salt_b64, digest_b64 = stored_hash.split("$", 1)
        salt = base64.b64decode(salt_b64.encode())
        expected = base64.b64decode(digest_b64.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 120_000)
        return hmac.compare_digest(actual, expected)
    except Exception:
        return False


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def create_token(user_id: int, username: str, role: str) -> str:
    """Create an HMAC-SHA256 signed bearer token."""
    payload = {
        "uid": user_id,
        "username": username,
        "role": role,
        "exp": int(time.time()) + int(current_app.config["TOKEN_TTL_SECONDS"]),
    }
    payload_b64 = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    secret = current_app.config["SECRET_KEY"].encode("utf-8")
    sig = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
    return f"{payload_b64}.{_b64url_encode(sig)}"


def verify_token(token: str) -> dict | None:
    """Validate token signature and expiration."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        secret = current_app.config["SECRET_KEY"].encode("utf-8")
        expected_sig = hmac.new(secret, payload_b64.encode("ascii"), hashlib.sha256).digest()
        if not hmac.compare_digest(_b64url_decode(sig_b64), expected_sig):
            return None
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def get_current_user_row(db):
    """Extract authenticated user from Authorization Bearer header."""
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:].strip()
    payload = verify_token(token)
    if not payload:
        return None
    user = db.execute(
        "SELECT id, username, full_name, email, role, department, is_active, created_at FROM users WHERE id = ?",
        (payload["uid"],),
    ).fetchone()
    if not user or not user["is_active"]:
        return None
    return dict(user)


def require_auth(fn):
    """Ensure request has a valid authenticated user."""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        from .db import get_db

        user = get_current_user_row(get_db())
        if not user:
            return jsonify({"error": "Authentication required"}), 401
        g.current_user = user
        return fn(*args, **kwargs)

    return wrapper


def require_roles(*roles):
    """Ensure authenticated user holds one of the allowed RBAC roles."""
    def decorator(fn):
        @wraps(fn)
        @require_auth
        def wrapper(*args, **kwargs):
            if g.current_user["role"] not in roles:
                return jsonify({"error": "Insufficient permissions for role"}), 403
            return fn(*args, **kwargs)

        return wrapper

    return decorator


class LoginRateLimiter:
    """Lightweight sliding-window brute-force protection for login gateways."""

    def __init__(self, max_attempts: int = 5, window_seconds: int = 300):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._failures: dict[str, list[float]] = {}

    def _prune(self, key: str, now: float) -> list[float]:
        cutoff = now - self.window_seconds
        entries = [t for t in self._failures.get(key, []) if t > cutoff]
        if entries:
            self._failures[key] = entries
        else:
            self._failures.pop(key, None)
        return entries

    def is_blocked(self, key: str) -> bool:
        return len(self._prune(key, time.time())) >= self.max_attempts

    def record_failure(self, key: str) -> int:
        now = time.time()
        entries = self._prune(key, now)
        entries.append(now)
        self._failures[key] = entries
        return len(entries)

    def clear(self, key: str):
        self._failures.pop(key, None)


login_rate_limiter = LoginRateLimiter()


def validate_password_strength(password: str) -> str | None:
    if len(password) < 8:
        return "Password must be at least 8 characters long"
    if not any(c.isupper() for c in password):
        return "Password must include at least one uppercase letter (A-Z)"
    if not any(c.islower() for c in password):
        return "Password must include at least one lowercase letter (a-z)"
    if not any(c.isdigit() for c in password):
        return "Password must include at least one numeric digit (0-9)"
    if not any(not c.isalnum() for c in password):
        return "Password must include at least one special character (!@#$%^&*)"
    return None

