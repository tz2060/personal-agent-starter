from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import init_db
from app.main import app


@pytest.fixture(autouse=True)
def clean_runtime():
    if config.DATA_DIR.exists():
        for child in config.DATA_DIR.iterdir():
            if child.is_file():
                child.unlink()
            elif child.is_dir():
                import shutil
                shutil.rmtree(child)
    for directory in (config.KNOWLEDGE_DIR, config.RULES_DIR, config.ATTACHMENTS_DIR, config.INBOX_DIR, config.VAULT_DIR / "topics"):
        if directory.exists():
            for child in directory.rglob("*"):
                if child.is_file():
                    child.unlink()
        directory.mkdir(parents=True, exist_ok=True)
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    init_db()
    yield


def test_health_and_dashboard_start():
    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        dashboard = client.get("/api/dashboard")
        assert dashboard.status_code == 200
        assert dashboard.json()["documents"] == 0


def test_text_ingest_search_and_duplicate_detection():
    with TestClient(app) as client:
        payload = {"title": "信念与预测模型", "content": "信念可以被理解为关于自我和世界的稳定预测模型。这个笔记还讨论了预测误差与学习。", "source_uri": "https://example.test/notes"}
        first = client.post("/api/documents/text", json=payload)
        assert first.status_code == 200, first.text
        assert first.json()["duplicate"] is False
        duplicate = client.post("/api/documents/text", json={**payload, "title": "重复笔记"})
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json()["duplicate"] is True
        assert duplicate.json()["doc_id"] == first.json()["doc_id"]
        results = client.get("/api/search", params={"q": "预测模型"})
        assert results.status_code == 200
        assert any(item["doc_id"] == first.json()["doc_id"] for item in results.json())


def test_rule_is_saved_as_markdown_and_returned_by_rules_api():
    with TestClient(app) as client:
        response = client.post("/api/rules", json={"title": "日期字段必须区分", "body": "不能把报名截止时间当作活动开始时间。没有活动开始时间时，写明未提供。"})
        assert response.status_code == 200, response.text
        relpath = response.json()["file_path"]
        assert (config.VAULT_DIR / relpath).exists()
        rules = client.get("/api/rules")
        assert rules.status_code == 200
        assert len(rules.json()) == 1
        assert "活动开始时间" in rules.json()[0]["content"]


def test_new_plain_markdown_file_is_indexed_and_resynced_after_external_edit():
    with TestClient(app) as client:
        config.KNOWLEDGE_DIR.mkdir(parents=True, exist_ok=True)
        note_path = config.KNOWLEDGE_DIR / "manual-note.md"
        note_path.write_text("# 手工笔记\n\n这份笔记包含银杏树知识。\n", encoding="utf-8")
        result = client.post("/api/reindex")
        assert result.status_code == 200
        docs = client.get("/api/documents").json()
        manual = next(row for row in docs if row["title"] == "manual-note")
        content = note_path.read_text(encoding="utf-8")
        assert '\nid: "' in content
        note_path.write_text(content + "\n新增词条：蓝莓特例。\n", encoding="utf-8")
        search = client.get("/api/search", params={"q": "蓝莓特例"})
        assert search.status_code == 200
        assert any(row["doc_id"] == manual["doc_id"] for row in search.json())


def test_markdown_edit_updates_index_immediately():
    with TestClient(app) as client:
        created = client.post("/api/documents/text", json={"title":"索引更新测试", "content":"原始关键词：火车站。"})
        doc_id = created.json()["doc_id"]
        item = client.get(f"/api/documents/{doc_id}").json()
        updated_markdown = item["markdown"].replace("原始关键词：火车站。", "修改后关键词：极光车站。").replace("# 摘要与核心要点", "# 摘要与核心要点")
        saved = client.put(f"/api/documents/{doc_id}", json={"markdown": updated_markdown})
        assert saved.status_code == 200, saved.text
        results = client.get("/api/search", params={"q":"极光车站"}).json()
        assert any(row["doc_id"] == doc_id for row in results)


def test_mail_sync_endpoint_is_safe_when_not_configured():
    with TestClient(app) as client:
        response = client.post("/api/mail/sync")
        assert response.status_code == 200
        assert response.json()["status"] == "skipped"
        assert "未配置" in response.json()["reason"]


def test_email_thread_dedupe_and_send_is_one_shot(monkeypatch):
    from email.message import EmailMessage as RawEmailMessage

    from app import mail_service
    from app.db import connect, now_iso

    class FakeSMTP:
        calls = 0

        def __init__(self, *args, **kwargs):
            pass

        def ehlo(self):
            return 250, b"ok"

        def login(self, user, password):
            return 235, b"ok"

        def send_message(self, message):
            type(self).calls += 1

        def quit(self):
            return 221, b"bye"

    monkeypatch.setattr(mail_service, "smtp_configured", lambda: True)
    monkeypatch.setattr(mail_service, "SMTP_HOST", "smtp.example.test")
    monkeypatch.setattr(mail_service, "SMTP_PORT", 465)
    monkeypatch.setattr(mail_service, "SMTP_USER", "agent@example.test")
    monkeypatch.setattr(mail_service, "SMTP_PASSWORD", "test-only")
    monkeypatch.setattr(mail_service, "MAIL_FROM", "agent@example.test")
    monkeypatch.setattr(mail_service.smtplib, "SMTP_SSL", FakeSMTP)

    first = RawEmailMessage()
    first["From"] = "Friend <friend@example.test>"
    first["To"] = "agent@example.test"
    first["Subject"] = "Planning"
    first["Message-ID"] = "<incoming-1@example.test>"
    first.set_content("Could we meet on Friday?")
    history = mail_service._store_email("validity-1", 1, first.as_bytes(), initial_status="HISTORY")
    assert history is not None
    assert mail_service._store_email("validity-1", 1, first.as_bytes(), initial_status="HISTORY") is None

    incoming = RawEmailMessage()
    incoming["From"] = "Friend <friend@example.test>"
    incoming["To"] = "agent@example.test"
    incoming["Subject"] = "Re: Planning"
    incoming["Message-ID"] = "<incoming-2@example.test>"
    incoming["In-Reply-To"] = "<incoming-1@example.test>"
    incoming["References"] = "<incoming-1@example.test>"
    incoming.set_content("Friday works for me. Please confirm the time.")
    new_mail = mail_service._store_email("validity-1", 2, incoming.as_bytes())
    assert new_mail is not None
    assert new_mail["thread_key"] == history["thread_key"]
    assert mail_service._create_draft(new_mail) is True
    assert mail_service._create_draft(new_mail) is False

    with connect() as con:
        email_row = con.execute("SELECT * FROM emails WHERE id=?", (new_mail["id"],)).fetchone()
        assert email_row["status"] == "DRAFT_READY"
        assert con.execute("SELECT COUNT(*) FROM drafts WHERE email_id=?", (new_mail["id"],)).fetchone()[0] == 1
        draft = con.execute("SELECT * FROM drafts WHERE email_id=?", (new_mail["id"],)).fetchone()

    sent = mail_service.send_confirmed_draft(draft["id"], "friend@example.test", "Re: Planning", "Yes, Friday at 14:00 works.")
    assert sent["status"] == "SENT"
    assert FakeSMTP.calls == 1
    with connect() as con:
        saved = con.execute("SELECT status FROM drafts WHERE id=?", (draft["id"],)).fetchone()
        source_status = con.execute("SELECT status FROM emails WHERE id=?", (new_mail["id"],)).fetchone()
        outbound = con.execute("SELECT * FROM emails WHERE message_id=?", (sent["outbound_message_id"],)).fetchone()
    assert saved["status"] == "SENT"
    assert source_status["status"] == "ANSWERED"
    assert outbound is not None and outbound["status"] == "SENT"
    with pytest.raises(ValueError, match="已经发送"):
        mail_service.send_confirmed_draft(draft["id"], "friend@example.test", "Re: Planning", "Yes, Friday at 14:00 works.")
    assert FakeSMTP.calls == 1


def test_uncertain_send_needs_manual_resolution_before_retry():
    from app import mail_service
    from app.db import connect, now_iso

    with connect() as con:
        cur = con.execute(
            """INSERT INTO emails(account,folder,uidvalidity,uid,message_id,thread_key,subject,sender,body,status,content_hash,created_at)
               VALUES('default','INBOX','v',55,'<src-uncertain@test>','<src-uncertain@test>','Question','friend@example.test','Original body','ANSWERED','test-hash','2026-10-19')"""
        )
        email_id = cur.lastrowid
        con.execute(
            """INSERT INTO drafts(id,email_id,version,recipient,subject,body,body_hash,status,approved_hash,outbound_message_id,created_at,updated_at)
               VALUES('draft-uncertain',?,1,'friend@example.test','Re: Question','Revised reply','hash','SEND_UNCERTAIN','hash','<attempt@test>','2026-10-19','2026-10-19')""",
            (email_id,),
        )
    outcome = mail_service.resolve_uncertain_send("draft-uncertain", "not_sent")
    assert outcome["status"] == "DRAFT"
    with connect() as con:
        row = con.execute("SELECT status,outbound_message_id,approved_hash FROM drafts WHERE id='draft-uncertain'").fetchone()
    assert row["status"] == "DRAFT"
    assert row["outbound_message_id"] == ""
    assert row["approved_hash"] == ""


def test_deleted_markdown_is_removed_from_search_index():
    with TestClient(app) as client:
        created = client.post("/api/documents/text", json={"title":"即将删除的资料", "content":"独特词汇：灰鲸档案。"})
        assert created.status_code == 200
        doc_id = created.json()["doc_id"]
        file_path = config.VAULT_DIR / created.json()["file_path"]
        assert file_path.exists()
        file_path.unlink()
        result = client.post("/api/reindex")
        assert result.status_code == 200
        assert result.json()["removed"] == 1
        search = client.get("/api/search", params={"q":"灰鲸档案"})
        assert search.status_code == 200
        assert not any(row["doc_id"] == doc_id for row in search.json())


def test_file_upload_keeps_original_attachment_and_source_uri():
    with TestClient(app) as client:
        response = client.post(
            "/api/documents/upload",
            data={"source_uri":"hand-upload://my-notes"},
            files={"file":("sample.md", b"# Upload test\n\nOriginal source material about moss and ecology.", "text/markdown")},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        item = client.get(f"/api/documents/{data['doc_id']}").json()
        assert item["source_uri"] == "hand-upload://my-notes"
        assert data["attachment"].startswith("attachments/")
        assert (config.VAULT_DIR / data["attachment"]).exists()


def test_password_protects_api_when_configured(monkeypatch):
    from app import main as main_module

    monkeypatch.setattr(main_module, "APP_PASSWORD", "unit-test-strong-password")
    with TestClient(app) as client:
        assert client.get("/api/dashboard").status_code == 401
        login = client.post("/api/login", json={"password":"wrong"})
        assert login.status_code == 401
        login = client.post("/api/login", json={"password":"unit-test-strong-password"})
        assert login.status_code == 200
        token = login.json()["token"]
        assert client.get("/api/dashboard", headers={"Authorization":f"Bearer {token}"}).status_code == 200


def test_imap_first_bootstrap_imports_history_without_drafting_old_mail(monkeypatch):
    from email.message import EmailMessage as RawEmailMessage

    from app import mail_service
    from app.db import connect

    def raw_message(msg_id: str, subject: str, body: str, parent: str = "") -> bytes:
        msg = RawEmailMessage()
        msg["From"] = "friend@example.test"
        msg["To"] = "owner@example.test"
        msg["Subject"] = subject
        msg["Message-ID"] = msg_id
        if parent:
            msg["In-Reply-To"] = parent
            msg["References"] = parent
        msg.set_content(body)
        return msg.as_bytes()

    messages = {
        1: raw_message("<old@test>", "Very old", "Old message excluded by backfill window."),
        2: raw_message("<root@test>", "Project", "Original project correspondence."),
        3: raw_message("<reply@test>", "Re: Project", "This belongs to the same thread.", "<root@test>"),
    }

    class FakeIMAP:
        def login(self, user, password): return "OK", [b"logged in"]
        def select(self, folder, readonly=True): return "OK", [b"3"]
        def response(self, name): return "UIDVALIDITY", [b"4242"]
        def logout(self): return "BYE", [b"done"]
        def uid(self, command, *args):
            if command == "SEARCH":
                criteria = args[-1]
                start = int(criteria.split(":", 1)[0])
                found = sorted(uid for uid in messages if uid >= start)
                return "OK", [" ".join(map(str, found)).encode()]
            if command == "FETCH":
                uid = int(args[0])
                return "OK", [(f"{uid} (RFC822)".encode(), messages[uid]), b")"]
            raise AssertionError(f"Unexpected IMAP command: {command} {args}")

    monkeypatch.setattr(mail_service, "mailbox_configured", lambda: True)
    monkeypatch.setattr(mail_service, "IMAP_INITIAL_BACKFILL", 2)
    monkeypatch.setattr(mail_service.imaplib, "IMAP4_SSL", lambda *args, **kwargs: FakeIMAP())

    first = mail_service.poll_mailbox_once()
    assert first["bootstrap"] is True
    assert first["history_imported"] == 2
    assert first["drafts_created"] == 0
    with connect() as con:
        assert con.execute("SELECT COUNT(*) FROM drafts").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM emails WHERE status='HISTORY'").fetchone()[0] == 2

    messages[4] = raw_message("<new@test>", "Re: Project", "Could you confirm the meeting time?", "<reply@test>")
    second = mail_service.poll_mailbox_once()
    assert second["new_messages"] == 1
    assert second["drafts_created"] == 1
    third = mail_service.poll_mailbox_once()
    assert third["new_messages"] == 0
    assert third["drafts_created"] == 0
    with connect() as con:
        draft_count = con.execute("SELECT COUNT(*) FROM drafts").fetchone()[0]
        source = con.execute("SELECT thread_key,status FROM emails WHERE message_id='<new@test>'").fetchone()
    assert draft_count == 1
    assert source["status"] == "DRAFT_READY"
    assert source["thread_key"] == "<root@test>"


def test_local_openai_compatible_model_allows_empty_api_key(monkeypatch):
    from app import model

    monkeypatch.setattr(model, "LLM_BASE_URL", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(model, "LLM_API_KEY", "")
    monkeypatch.setattr(model, "LLM_MODEL", "qwen-local")
    assert model.configured() is True

    monkeypatch.setattr(model, "LLM_BASE_URL", "https://example.test/v1")
    assert model.configured() is False
