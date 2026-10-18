from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .config import ATTACHMENTS_DIR, KNOWLEDGE_DIR, VAULT_DIR, prepare_dirs
from .db import connect, now_iso, transaction, log_operation
from .model import extract_image_text_or_summary, summarize_text

SUPPORTED_IMAGE = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
SUPPORTED_TEXT = {".txt", ".md", ".markdown", ".html", ".htm", ".csv", ".json", ".xml"}
SUPPORTED_PDF = {".pdf"}


class HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        elif tag in {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section"} and self.skip_depth == 0:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        elif tag in {"p", "div", "li", "h1", "h2", "h3", "h4", "tr", "section"} and self.skip_depth == 0:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.skip_depth == 0 and data.strip():
            self.parts.append(data.strip())


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def slugify(title: str) -> str:
    ascii_part = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()[:40]
    return ascii_part or "note"


def safe_title(value: str, fallback: str = "未命名资料") -> str:
    value = re.sub(r"[\x00-\x1f]+", " ", (value or "")).strip()
    return value[:180] or fallback


def _render_markdown(doc_id: str, title: str, source_type: str, source_uri: str,
                     content_hash: str, summary: str, raw_text: str,
                     attachment_relpath: str = "") -> str:
    captured = datetime.now(timezone.utc).isoformat(timespec="seconds")
    meta = {
        "id": doc_id, "title": title, "source_type": source_type,
        "source_uri": source_uri, "created_at": captured,
        "tags": [], "content_hash": content_hash, "status": "needs_review",
        "attachment": attachment_relpath,
    }
    frontmatter = "---\n" + "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in meta.items()
    ) + "\n---\n"
    return (frontmatter + f"\n# 摘要与核心要点\n\n{summary.strip() or '（待整理）'}\n"
            + "\n# 原文 / 提取内容\n\n" + (raw_text.strip() or "（未能自动提取文字；请查看原始附件。）")
            + (f"\n\n# 原始附件\n\n`{attachment_relpath}`\n" if attachment_relpath else "")
            + "\n# 个人理解与问题\n\n（可手动补充）\n"
            + "\n# 关联资料\n\n（可通过资料库检索后补充）\n"
            + f"\n# 来源与处理记录\n\n- 收集时间：{captured}\n- 来源：{source_uri or '未提供'}\n")


def ingest_document(title: str, raw_text: str, source_type: str = "note", source_uri: str = "",
                    original_hash: str | None = None, attachment_relpath: str = "",
                    summary_override: str | None = None) -> dict[str, Any]:
    prepare_dirs()
    title = safe_title(title)
    raw_text = (raw_text or "").strip()
    identity_hash = original_hash or sha256_text(raw_text)
    now = now_iso()
    with transaction(immediate=True) as con:
        existing = con.execute("SELECT * FROM documents WHERE content_hash=?", (identity_hash,)).fetchone()
        if existing:
            con.execute(
                "INSERT OR IGNORE INTO document_sources(doc_id,source_type,source_uri,captured_at) VALUES(?,?,?,?)",
                (existing["doc_id"], source_type, source_uri, now),
            )
            return {"doc_id": existing["doc_id"], "title": existing["title"],
                    "file_path": existing["file_path"], "duplicate": True,
                    "message": "检测到相同内容，已复用原文档并补记来源。"}

    summary = summary_override if summary_override is not None else summarize_text(title, raw_text)
    doc_id = "doc-" + uuid.uuid4().hex[:12]
    filename = f"{slugify(title)}--{doc_id[-6:]}.md"
    path = KNOWLEDGE_DIR / filename
    relpath = path.relative_to(VAULT_DIR).as_posix()
    markdown = _render_markdown(doc_id, title, source_type, source_uri, identity_hash,
                                summary, raw_text, attachment_relpath)
    path.write_text(markdown, encoding="utf-8")
    indexed_content = (summary + "\n" + raw_text).strip()
    try:
        with transaction(immediate=True) as con:
            cur = con.execute(
                "INSERT INTO documents(doc_id,title,source_type,source_uri,content_hash,file_path,content,summary,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (doc_id, title, source_type, source_uri, identity_hash, relpath,
                 indexed_content, summary, now, now),
            )
            rowid = cur.lastrowid
            con.execute("INSERT INTO documents_fts(rowid,title,content,doc_id) VALUES(?,?,?,?)",
                        (rowid, title, indexed_content, doc_id))
            con.execute(
                "INSERT OR IGNORE INTO document_sources(doc_id,source_type,source_uri,captured_at) VALUES(?,?,?,?)",
                (doc_id, source_type, source_uri, now),
            )
    except Exception:
        path.unlink(missing_ok=True)
        raise
    log_operation("document_ingested", "document", doc_id,
                  {"source_type": source_type, "content_hash": identity_hash})
    return {"doc_id": doc_id, "title": title, "file_path": relpath, "duplicate": False,
            "summary": summary, "message": "资料已写入 Markdown 并加入检索索引。"}


def ingest_text(title: str, body: str, source_uri: str = "", source_type: str = "note") -> dict[str, Any]:
    if not body.strip():
        raise ValueError("资料正文不能为空")
    return ingest_document(title, body, source_type, source_uri)


def extract_pdf(path: Path) -> str:
    try:
        reader = PdfReader(str(path))
        parts = []
        for page_no, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            if text:
                parts.append(f"\n[PDF 第 {page_no} 页]\n{text}")
        return "\n".join(parts).strip()
    except Exception as exc:
        return f"（PDF 文本提取失败：{type(exc).__name__}。原始文件仍已保存，请手动检查。）"


def extract_file_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in SUPPORTED_IMAGE:
        return extract_image_text_or_summary(path)
    if suffix in SUPPORTED_PDF:
        text = extract_pdf(path)
        if text:
            return text
        return "（PDF 似乎是扫描件或不含可提取文本。文件已保存；当前版本没有内置本地 OCR 引擎。）"
    if suffix in SUPPORTED_TEXT:
        raw = path.read_text(encoding="utf-8", errors="replace")
        if suffix in {".html", ".htm"}:
            parser = HTMLTextParser()
            parser.feed(raw)
            return "\n".join(parser.parts).strip()
        return raw
    return "（此格式暂未自动提取文字。原始附件已保存，可后续增加相应解析器。）"


def ingest_file(filename: str, data: bytes, source_uri: str = "") -> dict[str, Any]:
    prepare_dirs()
    basename = Path(filename or "upload.bin").name
    suffix = Path(basename).suffix.lower()[:12]
    content_hash = sha256_bytes(data)
    existing = None
    with connect() as con:
        existing = con.execute("SELECT doc_id,title,file_path FROM documents WHERE content_hash=?", (content_hash,)).fetchone()
    if existing:
        with connect() as con:
            con.execute("INSERT OR IGNORE INTO document_sources(doc_id,source_type,source_uri,captured_at) VALUES(?,?,?,?)",
                        (existing["doc_id"], "file", source_uri or basename, now_iso()))
        return {"doc_id": existing["doc_id"], "title": existing["title"],
                "file_path": existing["file_path"], "duplicate": True,
                "message": "该文件内容已导入，未创建重复文档。"}

    attachment_name = f"{content_hash[:16]}{suffix}"
    attachment_path = ATTACHMENTS_DIR / attachment_name
    attachment_path.write_bytes(data)
    rel_attachment = attachment_path.relative_to(VAULT_DIR).as_posix()
    extracted = extract_file_text(attachment_path)
    source_type = "image" if suffix in SUPPORTED_IMAGE else ("pdf" if suffix in SUPPORTED_PDF else "file")
    title = Path(basename).stem or "上传资料"
    if suffix in SUPPORTED_IMAGE and extracted.startswith("（图片原件已保存"):
        summary = extracted
    elif suffix in SUPPORTED_PDF and extracted.startswith("（PDF 似乎"):
        summary = extracted
    else:
        summary = None
    try:
        result = ingest_document(title, extracted, source_type, source_uri or basename,
                                 original_hash=content_hash, attachment_relpath=rel_attachment,
                                 summary_override=summary)
    except Exception:
        attachment_path.unlink(missing_ok=True)
        raise
    result["attachment"] = rel_attachment
    return result


def search_docs(query: str, limit: int = 8) -> list[dict[str, Any]]:
    query = (query or "").strip()
    if not query:
        return []
    limit = min(max(int(limit), 1), 20)
    tokens = re.findall(r"[\w\-]+", query, flags=re.UNICODE)
    fts_query = " AND ".join('"' + token.replace('"', '""') + '"' for token in tokens[:12])
    with connect() as con:
        rows = []
        if fts_query:
            try:
                rows = con.execute(
                    """SELECT d.doc_id,d.title,d.source_type,d.source_uri,d.file_path,d.summary,d.content,d.updated_at,
                              snippet(documents_fts,1,'[',']',' … ',18) AS snippet, bm25(documents_fts) AS rank
                       FROM documents_fts JOIN documents d ON d.id=documents_fts.rowid
                       WHERE documents_fts MATCH ? ORDER BY rank LIMIT ?""",
                    (fts_query, limit),
                ).fetchall()
            except Exception:
                rows = []
        if not rows:
            # Chinese notes often have no whitespace between terms, so an FTS5 token query
            # can be too strict. Fall back to substring matching over the whole query and
            # its whitespace-separated phrases, ranking documents that match more terms first.
            tokens_like = [x for x in re.split(r"\s+", query.strip()) if len(x) >= 1][:8]
            patterns = [f"%{query[:100]}%"] + [f"%{x[:80]}%" for x in tokens_like if x[:80] != query[:100]]
            clauses = " OR ".join(["title LIKE ? OR content LIKE ?" for _ in patterns])
            params: list[Any] = []
            for pattern in patterns:
                params.extend((pattern, pattern))
            rows = con.execute(
                f"""SELECT doc_id,title,source_type,source_uri,file_path,summary,content,updated_at,
                           substr(content,1,280) AS snippet, 0 AS rank
                    FROM documents WHERE {clauses} ORDER BY updated_at DESC LIMIT ?""",
                (*params, limit),
            ).fetchall()
    return [dict(row) for row in rows]


def get_document(doc_id: str) -> dict[str, Any] | None:
    with connect() as con:
        row = con.execute("SELECT * FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
    if not row:
        return None
    item = dict(row)
    full_path = VAULT_DIR / item["file_path"]
    item["markdown"] = full_path.read_text(encoding="utf-8") if full_path.exists() else ""
    return item


def _parse_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    """Read the small JSON-valued frontmatter format written by this app."""
    if not markdown.startswith("---\n"):
        return {}, markdown
    parts = markdown.split("\n---\n", 1)
    if len(parts) != 2:
        return {}, markdown
    metadata: dict[str, Any] = {}
    for line in parts[0][4:].splitlines():
        key, sep, value = line.partition(":")
        if not sep:
            continue
        try:
            metadata[key.strip()] = json.loads(value.strip())
        except json.JSONDecodeError:
            metadata[key.strip()] = value.strip().strip('"')
    return metadata, parts[1].lstrip("\n")


def _section_text(markdown_body: str, heading: str) -> str:
    pattern = rf"(?m)^#\s+{re.escape(heading)}\s*\n(.*?)(?=^#\s+|\Z)"
    match = re.search(pattern, markdown_body, flags=re.S)
    return match.group(1).strip() if match else ""


def _markdown_index_fields(markdown: str) -> tuple[dict[str, Any], str, str]:
    metadata, body = _parse_frontmatter(markdown)
    summary = _section_text(body, "摘要与核心要点")
    original = _section_text(body, "原文 / 提取内容")
    if not original:
        # A normal Markdown note authored by hand is still useful as source text.
        original = body.strip()
    indexed = "\n\n".join(part for part in (summary, original) if part).strip()
    if not summary:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", original) if p.strip()]
        summary = (paragraphs[0][:1200] if paragraphs else "")
    return metadata, indexed, summary


def sync_vault_index() -> dict[str, int]:
    """Re-index Markdown added or edited directly in the vault, without replacing source files."""
    prepare_dirs()
    scanned = added = updated = skipped = removed = 0
    roots = [(KNOWLEDGE_DIR, "note"), (VAULT_DIR / "rules", "rule"), (VAULT_DIR / "topics", "note")]
    # Paths are collected before parsing so a temporarily malformed file is not mistaken for a deletion.
    existing_paths = {path.relative_to(VAULT_DIR).as_posix() for root, _ in roots for path in root.rglob("*.md") if path.is_file()}
    for root, default_type in roots:
        for path in sorted(root.rglob("*.md")):
            if not path.is_file():
                continue
            scanned += 1
            try:
                markdown = path.read_text(encoding="utf-8")
                metadata, body = _parse_frontmatter(markdown)
                if not metadata.get("id"):
                    # Attach stable metadata to new hand-written Markdown notes once.
                    doc_id = "doc-" + sha256_text(path.relative_to(VAULT_DIR).as_posix())[:12]
                    title = safe_title(path.stem)
                    content_hash = sha256_text(markdown)
                    source_type = default_type
                    source_uri = path.relative_to(VAULT_DIR).as_posix()
                    created_at = datetime.fromtimestamp(path.stat().st_ctime, timezone.utc).isoformat(timespec="seconds")
                    metadata = {"id": doc_id, "title": title, "source_type": source_type,
                                "source_uri": source_uri, "created_at": created_at, "tags": [],
                                "content_hash": content_hash, "status": "needs_review"}
                    frontmatter = "---\n" + "\n".join(
                        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()
                    ) + "\n---\n\n"
                    markdown = frontmatter + body
                    path.write_text(markdown, encoding="utf-8")
                doc_id = safe_title(str(metadata.get("id", "")), "")
                if not doc_id:
                    skipped += 1
                    continue
                title = safe_title(str(metadata.get("title") or path.stem))
                source_type = str(metadata.get("source_type") or default_type)
                source_uri = str(metadata.get("source_uri") or path.relative_to(VAULT_DIR).as_posix())
                content_hash = str(metadata.get("content_hash") or sha256_text(markdown))
                created_at = str(metadata.get("created_at") or now_iso())
                _parsed_metadata, indexed, summary = _markdown_index_fields(markdown)
                relpath = path.relative_to(VAULT_DIR).as_posix()
                now = now_iso()
                with transaction(immediate=True) as con:
                    old = con.execute("SELECT id,title,content,summary,file_path,source_type,source_uri FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
                    if old:
                        changed = (old["content"] != indexed or old["summary"] != summary or old["file_path"] != relpath
                                   or old["title"] != title or old["source_type"] != source_type or old["source_uri"] != source_uri)
                        if not changed:
                            continue
                        con.execute("UPDATE documents SET title=?,source_type=?,source_uri=?,file_path=?,content=?,summary=?,updated_at=? WHERE doc_id=?",
                                    (title, source_type, source_uri, relpath, indexed, summary, now, doc_id))
                        con.execute("DELETE FROM documents_fts WHERE rowid=?", (old["id"],))
                        con.execute("INSERT INTO documents_fts(rowid,title,content,doc_id) VALUES(?,?,?,?)",
                                    (old["id"], title, indexed, doc_id))
                        updated += 1
                    else:
                        # Avoid a duplicate source hash blocking indexing if another file already represents it.
                        hash_owner = con.execute("SELECT doc_id FROM documents WHERE content_hash=?", (content_hash,)).fetchone()
                        if hash_owner and hash_owner["doc_id"] != doc_id:
                            skipped += 1
                            continue
                        cur = con.execute(
                            "INSERT INTO documents(doc_id,title,source_type,source_uri,content_hash,file_path,content,summary,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (doc_id, title, source_type, source_uri, content_hash, relpath, indexed, summary, created_at, now),
                        )
                        con.execute("INSERT INTO documents_fts(rowid,title,content,doc_id) VALUES(?,?,?,?)",
                                    (cur.lastrowid, title, indexed, doc_id))
                        con.execute("INSERT OR IGNORE INTO document_sources(doc_id,source_type,source_uri,captured_at) VALUES(?,?,?,?)",
                                    (doc_id, source_type, source_uri, now))
                        added += 1
            except Exception:
                skipped += 1
    # Markdown is the source of truth: a document deleted from the vault must not remain searchable.
    managed_prefixes = ("knowledge/", "rules/", "topics/")
    removed_files: list[str] = []
    with transaction(immediate=True) as con:
        rows = con.execute("SELECT id,doc_id,file_path FROM documents").fetchall()
        for row in rows:
            relpath = str(row["file_path"])
            if relpath.startswith(managed_prefixes) and relpath not in existing_paths:
                con.execute("DELETE FROM documents_fts WHERE rowid=?", (row["id"],))
                con.execute("DELETE FROM document_sources WHERE doc_id=?", (row["doc_id"],))
                con.execute("DELETE FROM documents WHERE doc_id=?", (row["doc_id"],))
                removed += 1
                removed_files.append(relpath)
    if removed:
        log_operation("documents_removed", "vault", "all", {"count": removed, "files": removed_files[:50]})
    return {"scanned": scanned, "added": added, "updated": updated, "removed": removed, "skipped": skipped}


def update_document_markdown(doc_id: str, markdown: str) -> dict[str, Any]:
    """Save user edits to the source Markdown and update the search index immediately."""
    if len(markdown.encode("utf-8")) > 2_000_000:
        raise ValueError("单个 Markdown 文档最大 2 MB")
    item = get_document(doc_id)
    if not item:
        raise KeyError("资料不存在")
    metadata, body = _parse_frontmatter(markdown)
    if metadata and str(metadata.get("id", "")) != doc_id:
        raise ValueError("文档元数据中的 id 与目标资料不一致")
    if not metadata:
        current_meta, _ = _parse_frontmatter(item.get("markdown", ""))
        metadata = current_meta or {"id": doc_id, "title": item["title"], "source_type": item["source_type"],
                                    "source_uri": item["source_uri"], "created_at": item["created_at"],
                                    "content_hash": item["content_hash"]}
        frontmatter = "---\n" + "\n".join(
            f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()
        ) + "\n---\n\n"
        markdown = frontmatter + body
    path = VAULT_DIR / item["file_path"]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    metadata, indexed, summary = _markdown_index_fields(markdown)
    new_title = safe_title(str(metadata.get("title") or item["title"]))
    new_source_type = str(metadata.get("source_type") or item["source_type"])
    new_source_uri = str(metadata.get("source_uri") or item["source_uri"])
    now = now_iso()
    with transaction(immediate=True) as con:
        row = con.execute("SELECT id FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if not row:
            raise KeyError("资料不存在")
        con.execute("UPDATE documents SET title=?,source_type=?,source_uri=?,content=?,summary=?,updated_at=? WHERE doc_id=?",
                    (new_title, new_source_type, new_source_uri, indexed, summary, now, doc_id))
        con.execute("DELETE FROM documents_fts WHERE rowid=?", (row["id"],))
        con.execute("INSERT INTO documents_fts(rowid,title,content,doc_id) VALUES(?,?,?,?)",
                    (row["id"], new_title, indexed, doc_id))
    log_operation("document_edited", "document", doc_id, {"file_path": item["file_path"]})
    return get_document(doc_id) or {}


def save_rule(title: str, body: str) -> dict[str, Any]:
    """Persist a correction as a readable Markdown rule so future tasks can reuse it."""
    prepare_dirs()
    title = safe_title(title, "长期规则")
    body = (body or "").strip()
    if not body:
        raise ValueError("规则内容不能为空")
    if len(body) > 12000:
        raise ValueError("规则内容最多 12000 个字符")
    doc_id = "rule-" + uuid.uuid4().hex[:12]
    content_hash = sha256_text(doc_id + "\n" + title + "\n" + body)
    created = now_iso()
    metadata = {"id": doc_id, "title": title, "source_type": "rule", "source_uri": "user-correction",
                "created_at": created, "tags": ["persistent-rule"], "content_hash": content_hash,
                "status": "active"}
    frontmatter = "---\n" + "\n".join(
        f"{key}: {json.dumps(value, ensure_ascii=False)}" for key, value in metadata.items()
    ) + "\n---\n\n"
    markdown = (frontmatter + f"# 摘要与核心要点\n\n适用于后续资料整理、检索回答和邮件草稿的长期规则。\n\n"
                + f"# 原文 / 提取内容\n\n{body}\n\n# 规则说明\n\n- 建立时间：{created}\n- 类型：用户纠正\n")
    path = (VAULT_DIR / "rules" / f"{slugify(title)}--{doc_id[-6:]}.md")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(markdown, encoding="utf-8")
    try:
        sync_result = sync_vault_index()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    log_operation("rule_saved", "rule", doc_id, {"title": title, "indexed": sync_result})
    return get_document(doc_id) or {"doc_id": doc_id, "title": title, "file_path": path.relative_to(VAULT_DIR).as_posix()}


def list_rules(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            "SELECT doc_id,title,source_uri,file_path,summary,content,updated_at FROM documents WHERE source_type='rule' ORDER BY updated_at DESC LIMIT ?",
            (min(max(limit, 1), 200),),
        ).fetchall()
    return [dict(row) for row in rows]


def list_documents(limit: int = 100) -> list[dict[str, Any]]:
    with connect() as con:
        rows = con.execute(
            "SELECT doc_id,title,source_type,source_uri,file_path,summary,updated_at FROM documents ORDER BY updated_at DESC LIMIT ?",
            (min(max(limit, 1), 200),),
        ).fetchall()
    return [dict(row) for row in rows]
