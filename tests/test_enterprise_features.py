"""Tests for enterprise features: Out of Office/Delegation, SLA Escalation, Multi-Currency,
Drafts, Request Withdrawal, Structured Rejections, Accounting CSV Export, User Lifecycle & Emails.
"""

from tests.conftest import auth_header


def test_multi_currency_policy_conversion(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")

    # 5,000 INR = ~$60 USD. Under expense policy auto_approve_max_amount ($100), so it auto-approves.
    res_inr = client.post(
        "/api/requests",
        headers=req_hdr,
        json={
            "request_type": "expense_report",
            "title": "Local travel reimbursement",
            "description": "Taxi cab travel to client site meeting",
            "amount": 5000,
            "currency": "INR",
            "urgency": "normal",
        },
    )
    assert res_inr.status_code == 201
    body_inr = res_inr.get_json()
    assert body_inr["status"] == "approved"
    assert body_inr["ai_evaluation"]["auto_approve_eligible"] is True

    # 350 EUR = ~$378 USD. Over $250 auto-approval threshold, routes to workflow.
    res_eur = client.post(
        "/api/requests",
        headers=req_hdr,
        json={
            "request_type": "expense_report",
            "title": "Software subscription",
            "description": "Monthly team dev subscription tool",
            "amount": 350,
            "currency": "EUR",
            "urgency": "normal",
        },
    )
    assert res_eur.status_code == 201
    assert res_eur.get_json()["status"] == "in_review"


def test_draft_lifecycle_and_withdrawal(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")

    # 1. Save as Draft
    draft_res = client.post(
        "/api/requests",
        headers=req_hdr,
        json={
            "request_type": "expense_report",
            "title": "Pending Conference Expenses",
            "description": "Draft expenses being collected",
            "amount": 450,
            "currency": "USD",
            "is_draft": True,
        },
    )
    assert draft_res.status_code == 201
    req_id = draft_res.get_json()["request_id"]
    assert draft_res.get_json()["status"] == "draft"
    assert draft_res.get_json()["is_draft"] is True

    # 2. Check draft in list
    drafts_list = client.get("/api/requests?status=draft", headers=req_hdr).get_json()["requests"]
    assert any(r["id"] == req_id for r in drafts_list)

    # 3. Edit Draft
    edit_res = client.put(
        f"/api/requests/{req_id}",
        headers=req_hdr,
        json={"title": "Updated Conference Expenses", "amount": 520},
    )
    assert edit_res.status_code == 200

    # 4. Submit Draft into active workflow
    submit_res = client.post(f"/api/requests/{req_id}/submit-draft", headers=req_hdr)
    assert submit_res.status_code == 200
    assert submit_res.get_json()["status"] in ("in_review", "approved")

    # 5. Withdraw Request
    withdraw_res = client.post(f"/api/requests/{req_id}/withdraw", headers=req_hdr)
    assert withdraw_res.status_code == 200
    assert withdraw_res.get_json()["status"] == "withdrawn"

    # Detail reflects withdrawn state
    detail = client.get(f"/api/requests/{req_id}", headers=req_hdr).get_json()["request"]
    assert detail["is_withdrawn"] is True
    assert detail["rejection_reason"] == "WITHDRAWN_BY_REQUESTER"


def test_structured_rejection_reasons(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")
    mgr_hdr = auth_header(client, "rohan.mehta", "MgrPass#2026")

    # Rejection reasons endpoint
    reasons = client.get("/api/rejection-reasons", headers=req_hdr).get_json()["rejection_reasons"]
    assert len(reasons) >= 5
    assert any(r["code"] == "BUDGET_EXCEEDED" for r in reasons)

    # Create request
    res = client.post(
        "/api/requests",
        headers=req_hdr,
        json={
            "request_type": "expense_report",
            "title": "Offsite team dinner",
            "description": "Quarterly team dinner celebration",
            "amount": 800,
            "currency": "USD",
        },
    )
    req_id = res.get_json()["request_id"]

    # Reject with structured reason
    rej = client.post(
        f"/api/requests/{req_id}/decision",
        headers=mgr_hdr,
        json={
            "decision": "rejected",
            "rejection_reason": "BUDGET_EXCEEDED",
            "comment": "Exceeds Q4 engineering social budget",
        },
    )
    assert rej.status_code == 200
    assert rej.get_json()["status"] == "rejected"

    detail = client.get(f"/api/requests/{req_id}", headers=req_hdr).get_json()
    assert detail["request"]["rejection_reason"] == "BUDGET_EXCEEDED"
    assert detail["approvals"][0]["rejection_reason"] == "BUDGET_EXCEEDED"


def test_approval_delegation_flow(client):
    mgr_hdr = auth_header(client, "rohan.mehta", "MgrPass#2026")
    apr_hdr = auth_header(client, "claire.chen", "AprPass#2026")
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")

    # Colleagues endpoint
    cols = client.get("/api/delegations/colleagues", headers=mgr_hdr).get_json()["colleagues"]
    claire = next(c for c in cols if c["username"] == "claire.chen")

    # Manager Rohan delegates approvals to Claire Chen (Finance Approver)
    create_del = client.post(
        "/api/delegations",
        headers=mgr_hdr,
        json={
            "delegate_user_id": claire["id"],
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "notes": "Annual vacation delegation",
        },
    )
    assert create_del.status_code == 201
    del_id = create_del.get_json()["id"]

    # Nadia submits request that requires manager approval
    sub = client.post(
        "/api/requests",
        headers=req_hdr,
        json={
            "request_type": "expense_report",
            "title": "Delegation Test Expense",
            "description": "Equipment test expense",
            "amount": 400,
            "currency": "USD",
        },
    )
    req_id = sub.get_json()["request_id"]

    # Claire (delegate) acts on behalf of manager Rohan to approve
    appr_res = client.post(
        f"/api/requests/{req_id}/decision",
        headers=apr_hdr,
        json={"decision": "approved", "comment": "Approved on behalf of Rohan"},
    )
    assert appr_res.status_code == 200

    # Revoke delegation
    rev = client.delete(f"/api/delegations/{del_id}", headers=mgr_hdr)
    assert rev.status_code == 200


def test_sla_escalation_and_email_logging(client):
    admin_hdr = auth_header(client, "sysadmin", "AdminGate#2026", is_admin=True)

    # Trigger SLA escalation sweep
    esc = client.post("/api/workflows/escalate", headers=admin_hdr)
    assert esc.status_code == 200
    assert "escalated_count" in esc.get_json()

    # Verify email dispatches endpoint
    emails = client.get("/api/notifications/emails", headers=admin_hdr).get_json()["emails"]
    assert isinstance(emails, list)


def test_user_lifecycle_password_reset_and_deactivation(client):
    admin_hdr = auth_header(client, "sysadmin", "AdminGate#2026", is_admin=True)
    users = client.get("/api/users", headers=admin_hdr).get_json()["users"]
    nadia = next(u for u in users if u["username"] == "nadia.patel")

    # 1. Admin resets Nadia's password
    reset_res = client.patch(
        f"/api/users/{nadia['id']}",
        headers=admin_hdr,
        json={"password": "NewSecretPass#2026"},
    )
    assert reset_res.status_code == 200

    # Nadia can log in with new password
    login_new = client.post(
        "/api/auth/login",
        json={"email": "nadia.patel@company.com", "password": "NewSecretPass#2026", "portal": "requester"},
    )
    assert login_new.status_code == 200

    # 2. Admin deactivates Nadia's account
    deactivate_res = client.patch(
        f"/api/users/{nadia['id']}",
        headers=admin_hdr,
        json={"is_active": False},
    )
    assert deactivate_res.status_code == 200
    assert deactivate_res.get_json()["is_active"] is False

    # Deactivated account cannot log in
    blocked = client.post(
        "/api/auth/login",
        json={"email": "nadia.patel@company.com", "password": "NewSecretPass#2026", "portal": "requester"},
    )
    assert blocked.status_code == 403
    assert "deactivated" in blocked.get_json()["error"].lower()

    # Reactivate Nadia's account
    reactivate_res = client.patch(
        f"/api/users/{nadia['id']}",
        headers=admin_hdr,
        json={"is_active": True},
    )
    assert reactivate_res.status_code == 200
    assert reactivate_res.get_json()["is_active"] is True


def test_user_self_service_profile_and_stats(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")

    # 1. Check me returns stats
    me_res = client.get("/api/auth/me", headers=req_hdr)
    assert me_res.status_code == 200
    user = me_res.get_json()["user"]
    assert "stats" in user
    assert "total_submitted" in user["stats"]

    # 2. Update own profile
    update_res = client.patch(
        "/api/auth/profile",
        headers=req_hdr,
        json={"full_name": "Nadia Patel-Kumar", "email": "nadia.kumar@company.com"},
    )
    assert update_res.status_code == 200
    assert update_res.get_json()["user"]["full_name"] == "Nadia Patel-Kumar"

    # 3. Change own password
    pwd_res = client.patch(
        "/api/auth/profile",
        headers=req_hdr,
        json={"current_password": "ReqPass#2026", "new_password": "MySelfPass#2026"},
    )
    assert pwd_res.status_code == 200

    # 4. Login with newly changed password
    login_res = client.post(
        "/api/auth/login",
        json={"email": "nadia.kumar@company.com", "password": "MySelfPass#2026", "portal": "requester"},
    )
    assert login_res.status_code == 200


def test_multi_receipt_attachments_upload(client):
    import io
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")

    f1 = (io.BytesIO(b"%PDF-1.4 flight receipt test"), "flight_ticket.pdf")
    f2 = (io.BytesIO(b"%PDF-1.4 hotel receipt test"), "hotel_invoice.pdf")

    res = client.post(
        "/api/requests",
        headers=req_hdr,
        data={
            "request_type": "expense_report",
            "title": "Dual Receipt Trip Expenses",
            "description": "Flight and lodging expenses",
            "amount": "850.00",
            "currency": "USD",
            "urgency": "normal",
            "attachment": [f1, f2],
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 201
    req_id = res.get_json()["request_id"]

    # Verify both attachments are stored and returned
    detail_res = client.get(f"/api/requests/{req_id}", headers=req_hdr)
    assert detail_res.status_code == 200
    attachments = detail_res.get_json()["attachments"]
    assert len(attachments) == 2
    filenames = [a["original_filename"] for a in attachments]
    assert "flight_ticket.pdf" in filenames
    assert "hotel_invoice.pdf" in filenames


def test_bulk_approvals_and_decisions(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")
    mgr_hdr = auth_header(client, "rohan.mehta", "MgrPass#2026")

    # Create two requests that exceed auto-approval limit ($250)
    r1 = client.post(
        "/api/requests",
        headers=req_hdr,
        json={"request_type": "expense_report", "title": "Batch Expense 1", "description": "Client lunch", "amount": 300, "currency": "USD"},
    ).get_json()["request_id"]

    r2 = client.post(
        "/api/requests",
        headers=req_hdr,
        json={"request_type": "expense_report", "title": "Batch Expense 2", "description": "Dev book bundle", "amount": 320, "currency": "USD"},
    ).get_json()["request_id"]

    # Manager bulk-approves both
    bulk_res = client.post(
        "/api/requests/bulk-decision",
        headers=mgr_hdr,
        json={"request_ids": [r1, r2], "decision": "approved", "comment": "Batch approval of quarterly expenses"},
    )
    assert bulk_res.status_code == 200
    assert bulk_res.get_json()["processed_count"] == 2


def test_volume_forecast_series(client):
    mgr_hdr = auth_header(client, "rohan.mehta", "MgrPass#2026")
    res = client.get("/api/analytics/predictions", headers=mgr_hdr)
    assert res.status_code == 200
    vf = res.get_json()["volume_forecast"]
    assert "forecast_series" in vf
    assert len(vf["forecast_series"]) == 7
    assert "count" in vf["forecast_series"][0]


def test_user_access_request_flow_pending_gating_and_approval(client):
    """Verify that employee access requests require admin dashboard approval before login."""
    # 1. Employee submits access request
    reg = client.post(
        "/api/auth/request-access",
        json={
            "full_name": "Arjun Patel",
            "username": "arjun.patel",
            "email": "arjun.patel@company.com",
            "department": "Engineering",
            "role": "manager",
            "password": "SecureAccess#2026",
        },
    )
    assert reg.status_code == 201
    assert reg.get_json()["status"] == "pending_approval"
    user_id = reg.get_json()["user"]["id"]

    # 2. User cannot log in while pending
    login_attempt = client.post(
        "/api/auth/login",
        json={"username": "arjun.patel", "password": "SecureAccess#2026"},
    )
    assert login_attempt.status_code == 403
    assert "pending" in login_attempt.get_json()["error"].lower()

    # 3. Admin views pending access requests
    admin_login = client.post(
        "/api/auth/admin/login",
        json={"username": "sysadmin", "password": "AdminGate#2026"},
    )
    assert admin_login.status_code == 200
    admin_hdr = {"Authorization": f"Bearer {admin_login.get_json()['token']}"}

    pending_list = client.get("/api/admin/access-requests", headers=admin_hdr)
    assert pending_list.status_code == 200
    requests = pending_list.get_json()["requests"]
    assert any(r["id"] == user_id and r["username"] == "arjun.patel" for r in requests)

    # 4. Admin approves access request and grants manager role
    decision = client.post(
        f"/api/admin/access-requests/{user_id}/decision",
        headers=admin_hdr,
        json={"decision": "approve", "role": "manager"},
    )
    assert decision.status_code == 200
    assert decision.get_json()["status"] == "active"
    assert decision.get_json()["role"] == "manager"

    # 5. User can now successfully log in with assigned role
    user_login = client.post(
        "/api/auth/login",
        json={"username": "arjun.patel", "password": "SecureAccess#2026"},
    )
    assert user_login.status_code == 200
    assert user_login.get_json()["user"]["role"] == "manager"
    assert "token" in user_login.get_json()


def test_user_access_request_rejection_flow(client):
    """Verify that rejected access requests remain blocked with rejection reason."""
    # 1. Submit request
    reg = client.post(
        "/api/auth/request-access",
        json={
            "full_name": "Spam User",
            "username": "spam.user",
            "email": "spam.user@external.com",
            "department": "Unknown",
            "password": "SecureAccess#2026",
        },
    )
    assert reg.status_code == 201
    user_id = reg.get_json()["user"]["id"]

    # 2. Admin declines request
    admin_login = client.post(
        "/api/auth/admin/login",
        json={"username": "sysadmin", "password": "AdminGate#2026"},
    )
    admin_hdr = {"Authorization": f"Bearer {admin_login.get_json()['token']}"}

    declined = client.post(
        f"/api/admin/access-requests/{user_id}/decision",
        headers=admin_hdr,
        json={"decision": "reject", "rejection_reason": "External email domain not allowed."},
    )
    assert declined.status_code == 200
    assert declined.get_json()["status"] == "rejected"

    # 3. User attempts to log in and gets rejection reason
    login_attempt = client.post(
        "/api/auth/login",
        json={"username": "spam.user", "password": "SecureAccess#2026"},
    )
    assert login_attempt.status_code == 403
    assert "rejected" in login_attempt.get_json()["error"].lower()
    assert "External email domain not allowed" in login_attempt.get_json()["error"]
