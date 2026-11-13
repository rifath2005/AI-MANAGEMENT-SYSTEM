"""Tests for project-tuned BYOK chat LLM routing, config RBAC, fallback, and fine-tuning dataset export."""

import json
from tests.conftest import auth_header


def test_chat_config_rbac_and_masking(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")
    admin_hdr = auth_header(client, "sysadmin", "AdminGate#2026", is_admin=True)

    cfg = client.get("/api/chat/config", headers=req_hdr).get_json()
    assert cfg["configured"] is False
    assert cfg["provider"] == "local_nlp"

    assert client.post("/api/chat/config", headers=req_hdr, json={"api_key": "sk-test12345678"}).status_code == 403

    save = client.post("/api/chat/config", headers=admin_hdr, json={"api_key": "sk-proj-1234567890abcd", "provider": "auto"})
    assert save.status_code == 200
    body = save.get_json()
    assert body["configured"] is True
    assert body["provider"] == "openai"
    assert body["masked_key"] == "sk-p...abcd"

    clr = client.post("/api/chat/config", headers=admin_hdr, json={"api_key": ""}).get_json()
    assert clr["configured"] is False


def test_project_tuned_llm_mock_and_fallback(client, monkeypatch):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")

    def fake_gemini(api_key, model, system_prompt, user_message):
        assert "Expense Policy" in system_prompt
        assert "Standard Expense Sequential" in system_prompt
        return json.dumps({"intent": "policy_qa", "reply": "Expense requests up to 250 USD auto-approve."})

    monkeypatch.setattr("app.chat_llm._call_gemini", fake_gemini)

    res = client.post(
        "/api/chat",
        headers={**req_hdr, "X-LLM-API-Key": "AIzaFakeGeminiKey12345"},
        json={"message": "What is our expense auto approval limit?"},
    )
    assert res.status_code == 200
    data = res.get_json()
    assert data["intent"] == "policy_qa"
    assert data["engine"].startswith("gemini:")
    assert "250" in data["reply"]

    def failing_gemini(*_args, **_kwargs):
        raise RuntimeError("Simulated API error")

    monkeypatch.setattr("app.chat_llm._call_gemini", failing_gemini)
    fb = client.post(
        "/api/chat",
        headers={**req_hdr, "X-LLM-API-Key": "AIzaFakeGeminiKey12345"},
        json={"message": "Submit expense report for $110 for team lunch"},
    )
    assert fb.status_code == 201
    assert fb.get_json()["engine"] == "local_nlp_fallback"


def test_finetune_dataset_export(client):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")

    r_openai = client.get("/api/chat/finetune-dataset?format=openai", headers=req_hdr)
    assert r_openai.status_code == 200
    lines = [json.loads(line) for line in r_openai.data.decode().strip().splitlines()]
    assert len(lines) >= 10
    assert "messages" in lines[0]

    r_gemini = client.get("/api/chat/finetune-dataset?format=gemini", headers=req_hdr)
    assert r_gemini.status_code == 200
    g_lines = [json.loads(line) for line in r_gemini.data.decode().strip().splitlines()]
    assert "text_input" in g_lines[0] and "output" in g_lines[0]
