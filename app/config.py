"""Application configuration for free-tier medium-load local or Supabase operation."""

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def load_env_file():
    """Load key-value pairs from .env file into os.environ if present."""
    env_file = BASE_DIR / ".env"
    if env_file.is_file():
        try:
            with open(env_file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("\"'")
                        if k and k not in os.environ:
                            os.environ[k] = v
        except Exception:
            pass


load_env_file()


class Config:
    SECRET_KEY = os.environ.get("AMS_SECRET_KEY", "dev-local-approval-mgmt-secret-change-in-prod")
    DATABASE_PATH = os.environ.get("AMS_DB_PATH", str(BASE_DIR / "data" / "approval_system.db"))
    UPLOAD_DIR = os.environ.get("AMS_UPLOAD_DIR", str(BASE_DIR / "data" / "uploads"))
    LOG_DIR = os.environ.get("AMS_LOG_DIR", str(BASE_DIR / "logs"))
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024  # 10 MB upload limit
    ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "txt", "csv", "doc", "docx", "xlsx"}
    TOKEN_TTL_SECONDS = 8 * 3600
    DEFAULT_SLA_HOURS = 48
    AI_RETRAIN_THRESHOLD = int(os.environ.get("AMS_AI_RETRAIN_THRESHOLD", "10"))
    TEMPLATES_AUTO_RELOAD = True
    SUPABASE_URL = os.environ.get("SUPABASE_URL", "").strip()
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "").strip()
    SUPABASE_BUCKET = os.environ.get("SUPABASE_BUCKET", "approval-attachments").strip()
