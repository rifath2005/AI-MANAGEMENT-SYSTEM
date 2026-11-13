"""Tests for local Scikit-learn AI/ML models, NLP parsing, forecasting, and optimization."""

from app.ai_engine import extract_nlp_metadata, parse_chat_command
from tests.conftest import auth_header


def test_nlp_extraction_and_chat_command_parsing():
    meta = extract_nlp_metadata("Urgent reimbursement for $420 flight ticket to client summit")
    assert meta["request_type"] == "expense_report"
    assert meta["amount"] == 420.0
    assert meta["urgency"] == "high"

    leave_meta = extract_nlp_metadata("Requesting 3 days annual leave next week")
    assert leave_meta["request_type"] == "leave_request"
    assert leave_meta["amount"] == 3.0

    cmd = parse_chat_command("Approve request #12 because receipts verified")
    assert cmd["intent"] == "approve_request"
    assert cmd["request_id"] == 12
    assert "receipts verified" in cmd["comment"]


def test_predictions_and_optimizations_endpoints(client):
    hdr = auth_header(client, "sysadmin", "AdminGate#2026", is_admin=True)

    pred_res = client.get("/api/analytics/predictions", headers=hdr)
    assert pred_res.status_code == 200
    pred = pred_res.get_json()
    assert len(pred["bottlenecks"]) >= 1
    assert pred["volume_forecast"]["predicted_next_7_days_requests"] >= 1

    opt_res = client.get("/api/analytics/optimizations", headers=hdr)
    assert opt_res.status_code == 200
    opt = opt_res.get_json()
    assert "workflow_optimizations" in opt
    assert "dynamic_rule_proposals" in opt
