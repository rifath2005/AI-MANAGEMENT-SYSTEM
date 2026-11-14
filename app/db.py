"""SQLite database schema, connection management, and realistic seed data."""

import hashlib
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from flask import current_app, g

from .security import hash_password

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('requester', 'manager', 'approver', 'hr', 'admin')),
    department TEXT NOT NULL DEFAULT 'General',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    request_type TEXT NOT NULL,
    execution_mode TEXT NOT NULL CHECK(execution_mode IN ('sequential', 'parallel')),
    min_amount REAL NOT NULL DEFAULT 0,
    max_amount REAL NOT NULL DEFAULT 1000000,
    stages_json TEXT NOT NULL,
    sla_hours INTEGER NOT NULL DEFAULT 48,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS policies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    request_type TEXT NOT NULL,
    auto_approve_max_amount REAL NOT NULL DEFAULT 0,
    require_attachment_above REAL NOT NULL DEFAULT 500,
    max_allowed_amount REAL NOT NULL DEFAULT 50000,
    blocked_keywords_json TEXT NOT NULL DEFAULT '[]',
    dynamic_adjustment_enabled INTEGER NOT NULL DEFAULT 1,
    is_active INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    requester_id INTEGER NOT NULL REFERENCES users(id),
    request_type TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    amount REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'USD',
    department TEXT NOT NULL DEFAULT 'General',
    urgency TEXT NOT NULL DEFAULT 'normal',
    status TEXT NOT NULL CHECK(status IN ('pending', 'in_review', 'approved', 'rejected', 'flagged')),
    workflow_id INTEGER REFERENCES workflows(id),
    current_stage_index INTEGER NOT NULL DEFAULT 0,
    ai_recommendation TEXT,
    ai_confidence REAL,
    ai_risk_score REAL,
    ai_explanation TEXT,
    is_anomaly INTEGER NOT NULL DEFAULT 0,
    anomaly_score REAL DEFAULT 0,
    anomaly_reasons_json TEXT DEFAULT '[]',
    nlp_extracted_json TEXT DEFAULT '{}',
    auto_approved INTEGER NOT NULL DEFAULT 0,
    due_at TEXT,
    amount_usd REAL DEFAULT 0,
    is_draft INTEGER NOT NULL DEFAULT 0,
    is_withdrawn INTEGER NOT NULL DEFAULT 0,
    rejection_reason TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS request_attachments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    original_filename TEXT NOT NULL,
    stored_filename TEXT NOT NULL,
    storage_backend TEXT NOT NULL DEFAULT 'local',
    content_type TEXT,
    size_bytes INTEGER NOT NULL,
    sha256_hash TEXT NOT NULL,
    uploaded_by INTEGER NOT NULL REFERENCES users(id),
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approval_tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    stage_index INTEGER NOT NULL,
    stage_name TEXT NOT NULL,
    assigned_role TEXT NOT NULL,
    assigned_user_id INTEGER REFERENCES users(id),
    status TEXT NOT NULL CHECK(status IN ('waiting', 'pending', 'approved', 'rejected', 'skipped')),
    is_escalated INTEGER NOT NULL DEFAULT 0,
    decision_by INTEGER REFERENCES users(id),
    comment TEXT,
    due_at TEXT,
    decided_at TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS approvals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id INTEGER NOT NULL REFERENCES requests(id) ON DELETE CASCADE,
    task_id INTEGER REFERENCES approval_tasks(id),
    approver_id INTEGER NOT NULL REFERENCES users(id),
    decision TEXT NOT NULL CHECK(decision IN ('approved', 'rejected', 'auto_approved')),
    rejection_reason TEXT,
    comment TEXT,
    cycle_time_hours REAL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request_id INTEGER REFERENCES requests(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    message TEXT NOT NULL,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS delegations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    delegate_user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    notes TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS email_dispatches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_email TEXT NOT NULL,
    recipient_name TEXT,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    category TEXT NOT NULL,
    request_id INTEGER REFERENCES requests(id) ON DELETE SET NULL,
    delivery_status TEXT NOT NULL DEFAULT 'simulated',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_id INTEGER REFERENCES users(id),
    actor_username TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    details_json TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_requests_status ON requests(status);
CREATE INDEX IF NOT EXISTS idx_requests_requester ON requests(requester_id);
CREATE INDEX IF NOT EXISTS idx_requests_created ON requests(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_request ON approval_tasks(request_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status_role ON approval_tasks(status, assigned_role);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);
CREATE INDEX IF NOT EXISTS idx_delegations_active ON delegations(delegate_user_id, is_active);
CREATE INDEX IF NOT EXISTS idx_email_dispatches ON email_dispatches(recipient_email, created_at);
"""


def utcnow_iso(offset_hours: float = 0) -> str:
    dt = datetime.now(timezone.utc) + timedelta(hours=offset_hours)
    return dt.replace(microsecond=0).isoformat()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        db_path = current_app.config["DATABASE_PATH"]
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES, timeout=10.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        g.db = conn
    return g.db


def close_db(_exc=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def append_audit_log(
    db: sqlite3.Connection,
    actor_id: int | None,
    actor_username: str,
    action: str,
    entity_type: str,
    entity_id: int | None,
    details: dict,
    created_at: str | None = None,
):
    """Append a hash-chained audit record so tampering is detectable."""
    ts = created_at or utcnow_iso()
    last = db.execute("SELECT entry_hash FROM audit_logs ORDER BY id DESC LIMIT 1").fetchone()
    prev_hash = last["entry_hash"] if last else "GENESIS"
    details_json = json.dumps(details, sort_keys=True)
    raw = f"{prev_hash}|{ts}|{actor_id}|{actor_username}|{action}|{entity_type}|{entity_id}|{details_json}"
    entry_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    db.execute(
        """
        INSERT INTO audit_logs (actor_id, actor_username, action, entity_type, entity_id, details_json, prev_hash, entry_hash, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (actor_id, actor_username, action, entity_type, entity_id, details_json, prev_hash, entry_hash, ts),
    )


def init_db(seed: bool = True):
    """Initialize schema and optionally populate seed data if empty."""
    db = get_db()
    db.executescript(SCHEMA_SQL)
    cols = {r["name"] for r in db.execute("PRAGMA table_info(request_attachments)").fetchall()}
    if "storage_backend" not in cols:
        db.execute("ALTER TABLE request_attachments ADD COLUMN storage_backend TEXT NOT NULL DEFAULT 'local'")

    req_cols = {r["name"] for r in db.execute("PRAGMA table_info(requests)").fetchall()}
    if "amount_usd" not in req_cols:
        db.execute("ALTER TABLE requests ADD COLUMN amount_usd REAL DEFAULT 0")
    if "is_draft" not in req_cols:
        db.execute("ALTER TABLE requests ADD COLUMN is_draft INTEGER NOT NULL DEFAULT 0")
    if "is_withdrawn" not in req_cols:
        db.execute("ALTER TABLE requests ADD COLUMN is_withdrawn INTEGER NOT NULL DEFAULT 0")
    if "rejection_reason" not in req_cols:
        db.execute("ALTER TABLE requests ADD COLUMN rejection_reason TEXT")

    appr_cols = {r["name"] for r in db.execute("PRAGMA table_info(approvals)").fetchall()}
    if "rejection_reason" not in appr_cols:
        db.execute("ALTER TABLE approvals ADD COLUMN rejection_reason TEXT")

    task_cols = {r["name"] for r in db.execute("PRAGMA table_info(approval_tasks)").fetchall()}
    if "is_escalated" not in task_cols:
        db.execute("ALTER TABLE approval_tasks ADD COLUMN is_escalated INTEGER NOT NULL DEFAULT 0")

    email_cols = {r["name"] for r in db.execute("PRAGMA table_info(email_dispatches)").fetchall()}
    if "delivery_status" not in email_cols:
        db.execute("ALTER TABLE email_dispatches ADD COLUMN delivery_status TEXT NOT NULL DEFAULT 'simulated'")

    if seed:
        existing_users = db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
        if existing_users == 0:
            seed_database(db)
    db.commit()


def seed_database(db: sqlite3.Connection, seed_mock_requests: bool | None = None):
    """Populate realistic users, workflows, policies, and optionally historical records if testing."""
    now = utcnow_iso()

    users = [
        ("nadia.patel", os.environ.get("AMS_SEED_REQ_PASS", "ReqPass#2026"), "Nadia Patel", "nadia.patel@company.com", "requester", "Engineering"),
        ("rohan.mehta", os.environ.get("AMS_SEED_MGR_PASS", "MgrPass#2026"), "Rohan Mehta", "rohan.mehta@company.com", "manager", "Engineering"),
        ("claire.chen", os.environ.get("AMS_SEED_APR_PASS", "AprPass#2026"), "Claire Chen", "claire.chen@company.com", "approver", "Finance"),
        ("david.okafor", os.environ.get("AMS_SEED_HR_PASS", "HrPass#2026"), "David Okafor", "david.okafor@company.com", "hr", "People Ops"),
        ("sysadmin", os.environ.get("AMS_SEED_ADMIN_PASS", "AdminGate#2026"), "Elena Vance (Admin)", "sysadmin@company.com", "admin", "IT Security"),
    ]
    user_ids = {}
    for uname, pwd, full_name, email, role, dept in users:
        cur = db.execute(
            """
            INSERT INTO users (username, password_hash, full_name, email, role, department, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (uname, hash_password(pwd), full_name, email, role, dept, now),
        )
        user_ids[uname] = cur.lastrowid

    workflows = [
        (
            "Standard Expense Sequential",
            "expense_report",
            "sequential",
            0,
            100000,
            json.dumps([
                {"name": "Manager Review", "role": "manager", "sla_hours": 24},
                {"name": "Finance Approval", "role": "approver", "sla_hours": 36},
            ]),
            48,
        ),
        (
            "Leave Request Approval",
            "leave_request",
            "sequential",
            0,
            365,
            json.dumps([
                {"name": "Manager Sign-Off", "role": "manager", "sla_hours": 24},
                {"name": "HR Verification", "role": "hr", "sla_hours": 24},
            ]),
            48,
        ),
        (
            "Purchase Order Parallel",
            "purchase_order",
            "parallel",
            0,
            500000,
            json.dumps([
                {"name": "Department Manager Review", "role": "manager", "sla_hours": 24},
                {"name": "Finance Approver Review", "role": "approver", "sla_hours": 36},
            ]),
            48,
        ),
    ]
    wf_ids = {}
    for name, rtype, mode, min_a, max_a, stages_json, sla in workflows:
        cur = db.execute(
            """
            INSERT INTO workflows (name, request_type, execution_mode, min_amount, max_amount, stages_json, sla_hours, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (name, rtype, mode, min_a, max_a, stages_json, sla, now),
        )
        wf_ids[rtype] = cur.lastrowid

    policies = [
        ("Expense Policy", "expense_report", 250.0, 300.0, 15000.0, json.dumps(["casino", "crypto", "personal gift", "unverified"]), 1),
        ("Leave Policy", "leave_request", 2.0, 5.0, 30.0, json.dumps(["unpaid emergency override"]), 1),
        ("Purchase Order Policy", "purchase_order", 500.0, 1000.0, 50000.0, json.dumps(["rush cash", "offshore", "no invoice"]), 1),
    ]
    for pname, rtype, auto_max, attach_above, max_allowed, blocked, dyn in policies:
        db.execute(
            """
            INSERT INTO policies (name, request_type, auto_approve_max_amount, require_attachment_above, max_allowed_amount, blocked_keywords_json, dynamic_adjustment_enabled, is_active, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
            """,
            (pname, rtype, auto_max, attach_above, max_allowed, blocked, dyn, now),
        )

    if seed_mock_requests is None:
        seed_mock_requests = os.environ.get("AMS_SEED_DEMO_DATA", "false").lower() == "true"
        try:
            from flask import current_app
            if current_app and current_app.config.get("TESTING"):
                seed_mock_requests = True
        except Exception:
            pass

    if not seed_mock_requests:
        append_audit_log(
            db, user_ids["sysadmin"], "sysadmin", "SYSTEM_INIT", "system", None,
            {"roles_seeded": len(users), "workflows_seeded": len(workflows), "mock_data": False}, now
        )
        return

    # Seed 30 historical requests across the last 30 days for ML training, forecasting & analytics
    historical_samples = [
        ("expense_report", "Team lunch meeting", "Lunch with engineering sprint team", 120, "Engineering", "normal", "approved", 4.5, True),
        ("expense_report", "Cloud training course", "Online workshop fee for developer", 180, "Engineering", "normal", "approved", 6.0, True),
        ("expense_report", "Client travel flight", "Round-trip airfare for client demo", 680, "Engineering", "normal", "approved", 18.0, False),
        ("expense_report", "Monitor replacement", "27 inch office monitor purchase", 340, "Engineering", "normal", "approved", 12.0, False),
        ("expense_report", "Urgent luxury dinner", "Unverified casino lounge dinner", 4800, "Engineering", "high", "rejected", 32.0, False),
        ("expense_report", "Conference ticket", "Annual Python conference pass", 450, "Engineering", "normal", "approved", 14.0, False),
        ("expense_report", "Software license", "IDE annual license renewal", 199, "Engineering", "normal", "approved", 2.0, True),
        ("expense_report", "Cab reimbursement", "Airport taxi receipts", 75, "Engineering", "normal", "approved", 1.5, True),
        ("expense_report", "Hotel stay 3 nights", "Lodging for customer summit", 890, "Engineering", "normal", "approved", 22.0, False),
        ("expense_report", "Crypto hardware wallet", "Personal gift crypto purchase", 3500, "Engineering", "high", "rejected", 28.0, False),
        ("leave_request", "Annual leave 1 day", "Personal day off on Friday", 1, "Engineering", "normal", "approved", 1.0, True),
        ("leave_request", "Annual leave 2 days", "Short family trip", 2, "Engineering", "normal", "approved", 2.0, True),
        ("leave_request", "Vacation 5 days", "Planned annual vacation week", 5, "Engineering", "normal", "approved", 16.0, False),
        ("leave_request", "Medical leave 3 days", "Dental surgery recovery", 3, "Engineering", "high", "approved", 8.0, False),
        ("leave_request", "Extended leave 25 days", "Unplanned long break during release", 25, "Engineering", "high", "rejected", 40.0, False),
        ("leave_request", "Sick leave 1 day", "Flu recovery day", 1, "Engineering", "normal", "approved", 0.5, True),
        ("leave_request", "Vacation 4 days", "Summer break days", 4, "Engineering", "normal", "approved", 19.0, False),
        ("purchase_order", "Office stationery", "Notebooks, markers, and printer paper", 220, "Engineering", "normal", "approved", 3.0, True),
        ("purchase_order", "Ergonomic chairs x3", "Chairs for new hires", 1200, "Engineering", "normal", "approved", 26.0, False),
        ("purchase_order", "Test server RAM", "Upgrade memory modules for QA lab", 480, "Engineering", "normal", "approved", 4.0, True),
        ("purchase_order", "Offshore rush cash", "No invoice urgent wire request", 19000, "Engineering", "high", "rejected", 44.0, False),
        ("purchase_order", "Design monitor batch", "Four calibrated displays for UX", 2400, "Engineering", "normal", "approved", 31.0, False),
        ("purchase_order", "Keyboard kit", "Mechanical keyboards for developers", 380, "Engineering", "normal", "approved", 3.5, True),
        ("purchase_order", "Vendor annual support", "Database support contract renewal", 4200, "Engineering", "normal", "approved", 38.0, False),
        ("expense_report", "Team coffee supplies", "Monthly espresso beans", 95, "Engineering", "normal", "approved", 1.0, True),
        ("expense_report", "Duplicate high claim", "Urgent unverified hardware reimbursement", 6200, "Engineering", "high", "rejected", 29.0, False),
        ("leave_request", "Half day leave", "Doctor appointment morning", 1, "Engineering", "normal", "approved", 0.5, True),
        ("purchase_order", "Webcam batch", "Conference room webcams", 420, "Engineering", "normal", "approved", 2.5, True),
        ("expense_report", "Workshop books", "Technical books for engineering team", 210, "Engineering", "normal", "approved", 2.0, True),
        ("purchase_order", "Staging GPU workstation", "Local ML training workstation", 3600, "Engineering", "normal", "approved", 34.0, False),
    ]

    for idx, (rtype, title, desc, amt, dept, urg, outcome, cycle_h, auto_app) in enumerate(historical_samples):
        days_ago = 30 - idx
        created_ts = utcnow_iso(offset_hours=-days_ago * 24)
        completed_ts = utcnow_iso(offset_hours=-days_ago * 24 + cycle_h)
        rec = "approve" if outcome == "approved" else "reject"
        risk = 0.12 if outcome == "approved" else 0.86
        anom = 0 if outcome == "approved" else 1
        cur = db.execute(
            """
            INSERT INTO requests (
                requester_id, request_type, title, description, amount, currency, department, urgency,
                status, workflow_id, current_stage_index, ai_recommendation, ai_confidence, ai_risk_score,
                ai_explanation, is_anomaly, anomaly_score, anomaly_reasons_json, nlp_extracted_json,
                auto_approved, due_at, created_at, updated_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, 'USD', ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_ids["nadia.patel"], rtype, title, desc, amt, dept, urg,
                outcome, wf_ids[rtype], rec, 0.91 if outcome == "approved" else 0.88, risk,
                "Historical seeded record", anom, 0.8 if anom else 0.1,
                json.dumps(["Blocked keyword / high amount outlier"] if anom else []),
                json.dumps({"amount": amt, "request_type": rtype}),
                1 if auto_app else 0, created_ts, created_ts, completed_ts, completed_ts,
            ),
        )
        req_id = cur.lastrowid
        approver_id = user_ids["rohan.mehta"] if rtype == "leave_request" else user_ids["claire.chen"]
        db.execute(
            """
            INSERT INTO approvals (request_id, task_id, approver_id, decision, comment, cycle_time_hours, created_at)
            VALUES (?, NULL, ?, ?, ?, ?, ?)
            """,
            (
                req_id,
                approver_id,
                "auto_approved" if auto_app else outcome,
                "Seeded historical outcome",
                cycle_h,
                completed_ts,
            ),
        )

    # Seed 2 active pending requests so approvers/managers immediately see work in queues
    pending_samples = [
        ("expense_report", "Cloud Summit Travel", "Flight and hotel for team tech conference", 740, "normal", "in_review", 0, False),
        ("purchase_order", "Urgent Offshore Wire", "Rush cash vendor transfer with no invoice", 18500, "high", "flagged", 1, True),
    ]
    for title_idx, (rtype, title, desc, amt, urg, status, anom, is_flag) in enumerate(pending_samples):
        created_ts = utcnow_iso(offset_hours=-(title_idx + 1) * 18)
        due_ts = utcnow_iso(offset_hours=24 - title_idx * 18)
        cur = db.execute(
            """
            INSERT INTO requests (
                requester_id, request_type, title, description, amount, currency, department, urgency,
                status, workflow_id, current_stage_index, ai_recommendation, ai_confidence, ai_risk_score,
                ai_explanation, is_anomaly, anomaly_score, anomaly_reasons_json, nlp_extracted_json,
                auto_approved, due_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'USD', 'Engineering', ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (
                user_ids["nadia.patel"], rtype, title, desc, amt, urg, status, wf_ids[rtype],
                "review" if is_flag else "approve",
                0.78,
                0.84 if is_flag else 0.28,
                "Flagged due to blocked keywords and high amount" if is_flag else "Matches standard travel pattern",
                anom,
                0.92 if is_flag else 0.14,
                json.dumps(["Blocked keyword match", "High amount anomaly"] if is_flag else []),
                json.dumps({"amount": amt, "request_type": rtype, "urgency": urg}),
                due_ts, created_ts, created_ts,
            ),
        )
        req_id = cur.lastrowid
        db.execute(
            """
            INSERT INTO approval_tasks (request_id, stage_index, stage_name, assigned_role, status, due_at, created_at)
            VALUES (?, 0, 'Manager Review', 'manager', 'pending', ?, ?)
            """,
            (req_id, due_ts, created_ts),
        )
        if rtype == "purchase_order":
            db.execute(
                """
                INSERT INTO approval_tasks (request_id, stage_index, stage_name, assigned_role, status, due_at, created_at)
                VALUES (?, 1, 'Finance Approver Review', 'approver', 'pending', ?, ?)
                """,
                (req_id, due_ts, created_ts),
            )
        if is_flag:
            for target_uname in ("rohan.mehta", "claire.chen", "sysadmin"):
                db.execute(
                    """
                    INSERT INTO notifications (user_id, request_id, category, title, message, is_read, created_at)
                    VALUES (?, ?, 'anomaly_alert', ?, ?, 0, ?)
                    """,
                    (
                        user_ids[target_uname],
                        req_id,
                        f"Anomaly Flagged: {title}",
                        f"Request #{req_id} ({amt} USD) flagged for review: blocked keywords & amount outlier.",
                        created_ts,
                    ),
                )

    append_audit_log(db, user_ids["sysadmin"], "sysadmin", "SYSTEM_SEED", "system", None, {"seeded_requests": len(historical_samples) + len(pending_samples)}, now)
