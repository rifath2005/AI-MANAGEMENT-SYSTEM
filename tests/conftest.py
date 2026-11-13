"""Pytest fixtures providing isolated app instances with temporary SQLite storage."""

import pytest
from app import create_app
from app.security import login_rate_limiter


@pytest.fixture()
def client(tmp_path, monkeypatch):
    login_rate_limiter._failures.clear()
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AMS_LLM_API_KEY", raising=False)
    app = create_app({
        "TESTING": True,
        "DATABASE_PATH": str(tmp_path / "test.db"),
        "UPLOAD_DIR": str(tmp_path / "uploads"),
        "LOG_DIR": str(tmp_path / "logs"),
        "SUPABASE_URL": "",
        "SUPABASE_KEY": "",
    })
    with app.test_client() as c:
        yield c


def auth_header(client, username: str, password: str, is_admin: bool = False) -> dict:
    endpoint = "/api/auth/admin/login" if is_admin else "/api/auth/login"
    res = client.post(endpoint, json={"username": username, "password": password})
    assert res.status_code == 200, res.get_json()
    token = res.get_json()["token"]
    return {"Authorization": f"Bearer {token}"}
