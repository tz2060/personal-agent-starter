from __future__ import annotations

import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


def env_path(name: str, default: str) -> Path:
    value = Path(os.getenv(name, default)).expanduser()
    return value if value.is_absolute() else (BASE_DIR / value).resolve()


APP_TITLE = os.getenv("APP_TITLE", "Personal Knowledge Agent")
HOST = os.getenv("HOST", "127.0.0.1").strip() or "127.0.0.1"
PORT = int(os.getenv("PORT", "8000"))
APP_PASSWORD = os.getenv("APP_PASSWORD", "").strip()
MAX_UPLOAD_MB = max(1, min(int(os.getenv("MAX_UPLOAD_MB", "15")), 100))
VAULT_SYNC_SECONDS = max(15, int(os.getenv("VAULT_SYNC_SECONDS", "45")))
DATA_DIR = env_path("DATA_DIR", "./data")
VAULT_DIR = env_path("VAULT_DIR", "./vault")
KNOWLEDGE_DIR = VAULT_DIR / "knowledge"
RULES_DIR = VAULT_DIR / "rules"
ATTACHMENTS_DIR = VAULT_DIR / "attachments"
INBOX_DIR = VAULT_DIR / "_inbox"
DB_PATH = DATA_DIR / "agent.sqlite3"

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1").rstrip("/")
LLM_API_KEY = os.getenv("LLM_API_KEY", "").strip()
LLM_MODEL = os.getenv("LLM_MODEL", "").strip()

MAIL_ACCOUNT = os.getenv("MAIL_ACCOUNT", "default").strip() or "default"
IMAP_HOST = os.getenv("IMAP_HOST", "").strip()
IMAP_PORT = int(os.getenv("IMAP_PORT", "993"))
IMAP_USER = os.getenv("IMAP_USER", "").strip()
IMAP_PASSWORD = os.getenv("IMAP_PASSWORD", "")
IMAP_FOLDER = os.getenv("IMAP_FOLDER", "INBOX")
IMAP_POLL_SECONDS = max(30, int(os.getenv("IMAP_POLL_SECONDS", "120")))
IMAP_INITIAL_BACKFILL = max(0, min(int(os.getenv("IMAP_INITIAL_BACKFILL", "80")), 1000))
SMTP_HOST = os.getenv("SMTP_HOST", "").strip()
SMTP_PORT = int(os.getenv("SMTP_PORT", "465"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_USE_SSL = os.getenv("SMTP_USE_SSL", "true").lower() in {"1", "true", "yes", "on"}
SMTP_STARTTLS = os.getenv("SMTP_STARTTLS", "false").lower() in {"1", "true", "yes", "on"}
MAIL_FROM = os.getenv("MAIL_FROM", "").strip()

# 可选：把单篇资料发布到 GitHub 仓库。留空则该功能在界面上不可用。
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "").strip()
GITHUB_REPO = os.getenv("GITHUB_REPO", "").strip()
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main").strip() or "main"
GITHUB_NOTES_DIR = os.getenv("GITHUB_NOTES_DIR", "notes").strip().strip("/") or "notes"


def prepare_dirs() -> None:
    for path in (DATA_DIR, KNOWLEDGE_DIR, RULES_DIR, ATTACHMENTS_DIR, INBOX_DIR, VAULT_DIR / "topics"):
        path.mkdir(parents=True, exist_ok=True)
