"""Tests for role-specific dashboards, Supabase storage adapter, and AI retrain caching."""

import io
from tests.conftest import auth_header


def test_role_specific_dashboards(client):
    for uname, pwd, is_adm, expected_key in [
        ("nadia.patel", "ReqPass#2026", False, "stats"),
        ("rohan.mehta", "MgrPass#2026", False, "queue"),
        ("claire.chen", "AprPass#2026", False, "queue"),
        ("david.okafor", "HrPass#2026", False, "extra"),
        ("sysadmin", "AdminGate#2026", True, "system"),
    ]:
        hdr = auth_header(client, uname, pwd, is_admin=is_adm)
        res = client.get("/api/analytics/role-dashboard", headers=hdr)
        assert res.status_code == 200
        body = res.get_json()
        assert expected_key in body


def test_supabase_storage_config_and_upload_mock(client, monkeypatch):
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")
    admin_hdr = auth_header(client, "sysadmin", "AdminGate#2026", is_admin=True)

    assert client.post("/api/storage/config", headers=req_hdr, json={"supabase_url": "https://x.supabase.co"}).status_code == 403

    cfg = client.post(
        "/api/storage/config",
        headers=admin_hdr,
        json={"supabase_url": "https://demo.supabase.co", "supabase_key": "sb-secret-key-1234", "bucket": "docs"},
    )
    assert cfg.status_code == 200
    assert cfg.get_json()["backend"] == "supabase"

    stored_objects = {}

    class FakeResp:
        def __init__(self, data=b"", status=200):
            self._data = data
            self.status = status

        def read(self):
            return self._data

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def fake_urlopen(req, timeout=15):
        if req.get_method() == "POST":
            stored_objects[req.full_url] = req.data
            return FakeResp(b'{"Key":"ok"}', 200)
        return FakeResp(stored_objects[req.full_url], 200)

    monkeypatch.setattr("app.storage.urllib.request.urlopen", fake_urlopen)

    up = client.post(
        "/api/requests",
        headers=req_hdr,
        data={
            "request_type": "expense_report",
            "title": "Supabase Receipt Test",
            "description": "Travel hotel receipt",
            "amount": "620",
            "attachment": (io.BytesIO(b"supabase-file-bytes"), "hotel.pdf"),
        },
        content_type="multipart/form-data",
    )
    assert up.status_code == 201
    req_id = up.get_json()["request_id"]

    detail = client.get(f"/api/requests/{req_id}", headers=req_hdr).get_json()
    att = detail["attachments"][0]
    assert att["storage_backend"] == "supabase"

    dl = client.get(f"/api/requests/{req_id}/attachments/{att['id']}", headers=req_hdr)
    assert dl.status_code == 200
    assert dl.data == b"supabase-file-bytes"


def test_ai_model_caching_and_manual_retrain(client):
    admin_hdr = auth_header(client, "sysadmin", "AdminGate#2026", is_admin=True)
    req_hdr = auth_header(client, "nadia.patel", "ReqPass#2026")

    assert client.post("/api/ai/retrain", headers=req_hdr).status_code == 403

    res = client.post("/api/ai/retrain", headers=admin_hdr)
    assert res.status_code == 200
    assert res.get_json()["trained"] is True
