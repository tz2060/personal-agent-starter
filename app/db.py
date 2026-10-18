from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from .config import DB_PATH, prepare_dirs


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    prepare_dirs()
    con = sqlite3.connect(DB_PATH, timeout=15, isolation_level=None)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA busy_timeout=15000")
    return con


@contextmanager
def transaction(immediate: bool = False) -> Iterator[sqlite3.Connection]:
    con = connect()
    try:
        con.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db() -> None:
    with connect() as con:
        con.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL UNIQUE,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_uri TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL UNIQUE,
                file_path TEXT NOT NULL,
                content TEXT NOT NULL,
                summary TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS documents_fts USING fts5(
                title, content, doc_id UNINDEXED, tokenize='unicode61'
            );
            CREATE TABLE IF NOT EXISTS document_sources (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_uri TEXT NOT NULL DEFAULT '',
                captured_at TEXT NOT NULL,
                UNIQUE(doc_id, source_type, source_uri)
            );
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                task_type TEXT NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                result_json TEXT NOT NULL DEFAULT '{}',
                error_text TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS emails (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account TEXT NOT NULL,
                folder TEXT NOT NULL,
                uidvalidity TEXT NOT NULL,
                uid INTEGER NOT NULL,
                message_id TEXT NOT NULL DEFAULT '',
                in_reply_to TEXT NOT NULL DEFAULT '',
                references_header TEXT NOT NULL DEFAULT '',
                thread_key TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                sender TEXT NOT NULL DEFAULT '',
                recipients TEXT NOT NULL DEFAULT '',
                sent_at TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'NEW',
                content_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(account, folder, uidvalidity, uid)
            );
            CREATE INDEX IF NOT EXISTS idx_emails_thread ON emails(account, thread_key, created_at);
            CREATE TABLE IF NOT EXISTS drafts (
                id TEXT PRIMARY KEY,
                email_id INTEGER NOT NULL REFERENCES emails(id),
                version INTEGER NOT NULL DEFAULT 1,
                recipient TEXT NOT NULL DEFAULT '',
                subject TEXT NOT NULL DEFAULT '',
                body TEXT NOT NULL DEFAULT '',
                body_hash TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'DRAFT',
                approved_hash TEXT NOT NULL DEFAULT '',
                outbound_message_id TEXT NOT NULL DEFAULT '',
                send_error TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                sent_at TEXT NOT NULL DEFAULT '',
                UNIQUE(email_id, version)
            );
            CREATE TABLE IF NOT EXISTS mail_sync_state (
                account TEXT NOT NULL,
                folder TEXT NOT NULL,
                uidvalidity TEXT NOT NULL DEFAULT '',
                last_uid INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(account, folder)
            );
            CREATE TABLE IF NOT EXISTS operation_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT NOT NULL,
                object_type TEXT NOT NULL,
                object_id TEXT NOT NULL,
                detail_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            """
        )


def log_operation(action: str, object_type: str, object_id: str, detail: dict[str, Any] | None = None) -> None:
    with connect() as con:
        con.execute(
            "INSERT INTO operation_log(action, object_type, object_id, detail_json, created_at) VALUES(?,?,?,?,?)",
            (action, object_type, object_id, json.dumps(detail or {}, ensure_ascii=False), now_iso()),
        )


def upsert_task(task_id: str, task_type: str, title: str, status: str,
                payload: dict[str, Any] | None = None, result: dict[str, Any] | None = None,
                error_text: str = "") -> None:
    now = now_iso()
    with connect() as con:
        con.execute(
            """INSERT INTO tasks(id,task_type,title,status,payload_json,result_json,error_text,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,
               result_json=excluded.result_json,error_text=excluded.error_text,updated_at=excluded.updated_at""",
            (task_id, task_type, title, status,
             json.dumps(payload or {}, ensure_ascii=False), json.dumps(result or {}, ensure_ascii=False),
             error_text, now, now),
        )
