#!/usr/bin/env python3
"""Verification & diagnostics script for Approval Management System (AMS).
Tests .env variables, Groq AI connectivity, Supabase Storage, and local database.
"""

import json
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def load_env():
    env_file = BASE_DIR / ".env"
    if env_file.is_file():
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    k = k.strip()
                    v = v.strip().strip("\"'")
                    if k and k not in os.environ:
                        os.environ[k] = v


def check_database():
    print("\n--- 1. SQLite Database Check ---")
    db_path = BASE_DIR / "data" / "approval_system.db"
    if not db_path.exists():
        print(f"[FAIL] Database file not found at {db_path}")
        return False
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    user_count = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    print(f"[OK] Database connected ({db_path})")
    print(f"[OK] Found {len(tables)} tables: {', '.join(tables[:6])}...")
    print(f"[OK] {user_count} core role accounts initialized")
    return True


def check_groq_ai():
    print("\n--- 2. Groq AI Connectivity Check ---")
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        print("[INFO] GROQ_API_KEY is not set. Built-in Local NLP will be used.")
        return True

    masked = f"{api_key[:4]}...{api_key[-4:]}"
    print(f"[INFO] Testing Groq Key: {masked}")

    url = "https://api.groq.com/openai/v1/chat/completions"
    payload = {
        "model": "openai/gpt-oss-120b",
        "temperature": 0.1,
        "messages": [
            {"role": "system", "content": "You are AMS AI. Return JSON: {\"status\":\"ok\"}"},
            {"role": "user", "content": "ping"}
        ]
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "User-Agent": "AMS-Approval-System/1.0"
        },
        method="POST"
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            reply = data["choices"][0]["message"]["content"]
            print(f"[OK] Groq AI Connected Successfully! Model: openai/gpt-oss-120b")
            print(f"[OK] Response: {reply.strip()}")
            return True
    except urllib.error.HTTPError as e:
        print(f"[ERROR] Groq API returned HTTP {e.code}: {e.read().decode('utf-8')[:200]}")
        return False
    except Exception as e:
        print(f"[ERROR] Connection failed: {e}")
        return False


def check_supabase():
    print("\n--- 3. Supabase Cloud Storage Check ---")
    raw_url = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    key = os.environ.get("SUPABASE_KEY", "").strip()
    bucket = os.environ.get("SUPABASE_BUCKET", "approval-attachments").strip()

    if not raw_url or not key:
        print("[INFO] Supabase not configured in .env. Using zero-cost local disk storage in data/uploads/.")
        return True

    # Sanitize URL if user included /rest/v1
    import re
    base_url = re.sub(r"/rest(/v1)?/?$", "", raw_url)
    masked_key = f"{key[:4]}...{key[-4:]}"
    print(f"[INFO] Supabase Base URL: {base_url}")
    print(f"[INFO] Supabase Key: {masked_key}")
    print(f"[INFO] Target Bucket: {bucket}")

    req = urllib.request.Request(
        f"{base_url}/storage/v1/bucket",
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
            "User-Agent": "AMS-Approval-System/1.0"
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            buckets = json.loads(resp.read().decode("utf-8"))
            bucket_names = [b.get("id") or b.get("name") for b in buckets] if isinstance(buckets, list) else []
            print(f"[OK] Supabase API Connected Successfully!")
            print(f"[INFO] Existing Buckets in Project: {bucket_names or 'None yet'}")
            if bucket in bucket_names:
                print(f"[OK] Target bucket '{bucket}' is active and ready for uploads.")
            else:
                print(f"[NOTE] Bucket '{bucket}' has not been created yet in your Supabase dashboard.")
                print(f"       Action: In your Supabase Dashboard -> Storage -> Create new bucket named '{bucket}'.")
                print(f"       (Don't worry: The app will safely store attachments on local disk until the bucket is created).")
            return True
    except urllib.error.HTTPError as e:
        print(f"[ERROR] Supabase API returned HTTP {e.code}: {e.read().decode('utf-8')[:200]}")
        return False
    except Exception as e:
        print(f"[ERROR] Supabase connection failed: {e}")
        return False


if __name__ == "__main__":
    load_env()
    print("=" * 60)
    print("   APPROVAL MANAGEMENT SYSTEM (AMS) — DIAGNOSTIC CHECK")
    print("=" * 60)
    db_ok = check_database()
    ai_ok = check_groq_ai()
    sb_ok = check_supabase()
    print("\n" + "=" * 60)
    print(f"STATUS SUMMARY: Database={'PASS' if db_ok else 'FAIL'} | AI={'PASS' if ai_ok else 'FAIL'} | Storage={'PASS' if sb_ok else 'FAIL'}")
    print("=" * 60)
