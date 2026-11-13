"""End-to-end API tests covering sequential/parallel workflows, auto-approval, anomaly alerts, uploads, chat, and audit."""

import io
from tests.conftest import auth_header


def test_auto_approval_for_low_risk_request(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")
    res = client.post(
        "/api/requests",
        headers=req_hdr,
        json={
            "request_type": "expense_report",
            "title": "Team lunch",
            "description": "Lunch with engineering team for sprint demo",
            "amount": 95,
            "urgency": "normal",
        },
    )
    assert res.status_code == 201
    body = res.get_json()
    assert body["status"] == "approved"
    assert body["ai_evaluation"]["auto_approve_eligible"] is True


def test_sequential_multi_level_approval_and_attachment(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")
    mgr_hdr = auth_header(client, "rohan.mehta", "MgrPass#2026")
    apr_hdr = auth_header(client, "claire.chen", "AprPass#2026")

    res = client.post(
        "/api/requests",
        headers=req_hdr,
        data={
            "request_type": "expense_report",
            "title": "Tech conference travel",
            "description": "Flight and hotel for developer conference",
            "amount": "700",
            "urgency": "normal",
            "attachment": (io.BytesIO(b"receipt-pdf-content"), "receipt.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert res.status_code == 201
    req_id = res.get_json()["request_id"]
    assert res.get_json()["status"] == "in_review"

    early = client.post(
        f"/api/requests/{req_id}/decision",
        headers=apr_hdr,
        json={"decision": "approved", "comment": "Too early"},
    )
    assert early.status_code == 403

    s1 = client.post(
        f"/api/requests/{req_id}/decision",
        headers=mgr_hdr,
        json={"decision": "approved", "comment": "Manager ok"},
    )
    assert s1.status_code == 200
    assert s1.get_json()["status"] == "in_review"

    s2 = client.post(
        f"/api/requests/{req_id}/decision",
        headers=apr_hdr,
        json={"decision": "approved", "comment": "Finance ok"},
    )
    assert s2.status_code == 200
    assert s2.get_json()["status"] == "approved"

    detail = client.get(f"/api/requests/{req_id}", headers=req_hdr).get_json()
    assert len(detail["attachments"]) == 1
    att_id = detail["attachments"][0]["id"]
    dl = client.get(f"/api/requests/{req_id}/attachments/{att_id}", headers=req_hdr)
    assert dl.status_code == 200
    assert dl.data == b"receipt-pdf-content"


def test_parallel_workflow_and_rejection(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")
    mgr_hdr = auth_header(client, "rohan.mehta", "MgrPass#2026")
    apr_hdr = auth_header(client, "claire.chen", "AprPass#2026")

    res = client.post(
        "/api/requests",
        headers=req_hdr,
        json={
            "request_type": "purchase_order",
            "title": "Team monitors",
            "description": "Two calibrated office monitors for design team",
            "amount": 950,
            "urgency": "normal",
        },
    )
    req_id = res.get_json()["request_id"]
    detail = client.get(f"/api/requests/{req_id}", headers=mgr_hdr).get_json()
    assert all(t["status"] == "pending" for t in detail["tasks"])

    r1 = client.post(
        f"/api/requests/{req_id}/decision",
        headers=apr_hdr,
        json={"decision": "approved", "comment": "Budget available"},
    )
    assert r1.status_code == 200
    assert r1.get_json()["status"] == "in_review"

    r2 = client.post(
        f"/api/requests/{req_id}/decision",
        headers=mgr_hdr,
        json={"decision": "rejected", "comment": "Defer to next quarter"},
    )
    assert r2.status_code == 200
    assert r2.get_json()["status"] == "rejected"


def test_anomaly_detection_chat_sweep_export_and_audit(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")
    admin_hdr = auth_header(client, "sysadmin", "AdminGate#2026", is_admin=True)

    chat_res = client.post(
        "/api/chat",
        headers=req_hdr,
        json={"message": "Submit urgent expense report for $9500 at casino lounge unverified"},
    )
    assert chat_res.status_code == 201
    chat_data = chat_res.get_json()["data"]
    assert chat_data["status"] == "flagged"
    assert chat_data["ai_evaluation"]["is_anomaly"] is True

    notifs = client.get("/api/notifications", headers=admin_hdr).get_json()["notifications"]
    assert any(n["category"] == "anomaly_alert" for n in notifs)

    sweep = client.post("/api/notifications/sweep", headers=admin_hdr)
    assert sweep.status_code == 200

    csv_res = client.get("/api/analytics/export.csv", headers=admin_hdr)
    assert csv_res.status_code == 200
    assert "text/csv" in csv_res.content_type

    verify = client.get("/api/audit/verify", headers=admin_hdr).get_json()
    assert verify["valid"] is True
