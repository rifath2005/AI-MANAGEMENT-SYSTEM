"""Convenient storage adapter: free-tier Supabase Storage with automatic local disk fallback."""

import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from flask import current_app
from werkzeug.utils import secure_filename


import re


def get_storage_config(db) -> dict:
    saved = {
        r["key"]: r["value"]
        for r in db.execute("SELECT key, value FROM app_settings WHERE key LIKE 'supabase_%'").fetchall()
    }
    raw_url = (saved.get("supabase_url") or current_app.config.get("SUPABASE_URL", "")).strip().rstrip("/")
    # Sanitize URL if user pasted the PostgREST /rest/v1 URL instead of base URL
    url = re.sub(r"/rest(/v1)?/?$", "", raw_url)
    key = (saved.get("supabase_key") or current_app.config.get("SUPABASE_KEY", "")).strip()
    bucket = (saved.get("supabase_bucket") or current_app.config.get("SUPABASE_BUCKET", "approval-attachments")).strip()
    enabled = bool(url and key and bucket)
    return {
        "backend": "supabase" if enabled else "local",
        "supabase_configured": enabled,
        "supabase_url": url,
        "bucket": bucket,
        "masked_key": f"{key[:4]}...{key[-4:]}" if len(key) > 8 else ("***" if key else ""),
        "_key": key,
    }


def save_attachment_bytes(db, req_id: int, original_filename: str, file_bytes: bytes, content_type: str | None) -> dict:
    """Store attachment in Supabase Storage when configured, otherwise local disk."""
    safe_name = secure_filename(original_filename) or "attachment.bin"
    object_name = f"req_{req_id}/{uuid.uuid4().hex[:8]}_{safe_name}"
    cfg = get_storage_config(db)

    if cfg["supabase_configured"]:
        endpoint = f"{cfg['supabase_url']}/storage/v1/object/{urllib.parse.quote(cfg['bucket'])}/{object_name}"
        req = urllib.request.Request(
            endpoint,
            data=file_bytes,
            headers={
                "Authorization": f"Bearer {cfg['_key']}",
                "apikey": cfg["_key"],
                "Content-Type": content_type or "application/octet-stream",
                "x-upsert": "true",
                "User-Agent": "AMS-Approval-System/1.0",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                if 200 <= resp.status < 300:
                    return {"backend": "supabase", "stored_filename": object_name, "original_filename": safe_name}
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
            # Fall back to local disk rather than losing user upload
            pass

    upload_dir = current_app.config["UPLOAD_DIR"]
    os.makedirs(upload_dir, exist_ok=True)
    flat_name = object_name.replace("/", "_")
    full_path = os.path.join(upload_dir, flat_name)
    with open(full_path, "wb") as f:
        f.write(file_bytes)
    return {"backend": "local", "stored_filename": flat_name, "original_filename": safe_name}


def fetch_attachment_bytes(db, stored_filename: str, backend: str = "local") -> bytes | None:
    """Retrieve attachment bytes from Supabase Storage or local disk."""
    if backend == "supabase":
        cfg = get_storage_config(db)
        if cfg["supabase_configured"]:
            endpoint = f"{cfg['supabase_url']}/storage/v1/object/{urllib.parse.quote(cfg['bucket'])}/{stored_filename}"
            req = urllib.request.Request(
                endpoint,
                headers={
                    "Authorization": f"Bearer {cfg['_key']}",
                    "apikey": cfg["_key"],
                    "User-Agent": "AMS-Approval-System/1.0",
                },
                method="GET",
            )
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    return resp.read()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
                return None

    full_path = os.path.join(current_app.config["UPLOAD_DIR"], stored_filename)
    if not os.path.exists(full_path):
        return None
    with open(full_path, "rb") as f:
        return f.read()
