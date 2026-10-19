"""把单篇资料发布到 GitHub 仓库。

用 REST Contents API 而不是 git 命令，原因有两点：
1. 不依赖运行服务那台机器上的 git 凭据助手（GCM 会弹窗，服务进程里拿不到）；
2. `vault/knowledge/` 在 .gitignore 里，走 git 需要 `-f` 强制添加，容易误伤整批私人文件。
单篇、显式、可回退，比批量 git add 更符合这个项目「原文是资产」的定位。
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import GITHUB_BRANCH, GITHUB_NOTES_DIR, GITHUB_REPO, GITHUB_TOKEN

API_ROOT = "https://api.github.com"
TIMEOUT_SECONDS = 30


class PublishError(RuntimeError):
    """发布过程中的可预期错误，调用方据此返回 502 与可读提示。"""


def configured() -> bool:
    return bool(GITHUB_TOKEN) and GITHUB_REPO.count("/") == 1


def _call(method: str, path: str, payload: dict[str, Any] | None = None) -> tuple[int, Any]:
    """调用 GitHub API，返回 (状态码, 解析后的 JSON)。HTTP 错误不抛异常，交由调用方判断。"""
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(API_ROOT + path, data=data, method=method)
    request.add_header("Authorization", f"Bearer {GITHUB_TOKEN}")
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            body = response.read().decode("utf-8", "replace")
            return response.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as exc:
        body = exc.read(2000).decode("utf-8", "replace")
        try:
            message = json.loads(body).get("message", body)
        except Exception:
            message = body
        return exc.code, {"message": message}
    except (urllib.error.URLError, TimeoutError) as exc:
        raise PublishError(f"无法连接 GitHub：{exc}") from exc


def publish_markdown(filename: str, markdown: str, commit_message: str) -> dict[str, Any]:
    """把一篇 Markdown 写到 `{GITHUB_NOTES_DIR}/{filename}`，已存在则覆盖并生成新提交。"""
    if not configured():
        raise PublishError("未配置 GITHUB_TOKEN 或 GITHUB_REPO（格式应为 owner/repo）")

    target_path = f"{GITHUB_NOTES_DIR}/{filename}"
    contents_path = f"/repos/{GITHUB_REPO}/contents/{urllib.parse.quote(target_path)}"

    # 覆盖已有文件时必须带 sha，否则 GitHub 返回 422。
    status, existing = _call("GET", f"{contents_path}?ref={urllib.parse.quote(GITHUB_BRANCH)}")
    sha = existing.get("sha") if status == 200 and isinstance(existing, dict) else None
    if status not in (200, 404):
        detail = existing.get("message") if isinstance(existing, dict) else ""
        raise PublishError(f"读取远端文件失败（HTTP {status}）：{detail}")

    payload: dict[str, Any] = {
        "message": commit_message,
        "content": base64.b64encode(markdown.encode("utf-8")).decode("ascii"),
        "branch": GITHUB_BRANCH,
    }
    if sha:
        payload["sha"] = sha

    status, result = _call("PUT", contents_path, payload)
    if status not in (200, 201) or not isinstance(result, dict):
        detail = result.get("message") if isinstance(result, dict) else ""
        raise PublishError(f"发布失败（HTTP {status}）：{detail}")

    content = result.get("content") or {}
    commit = result.get("commit") or {}
    return {
        "repo": GITHUB_REPO,
        "branch": GITHUB_BRANCH,
        "path": content.get("path", target_path),
        "url": content.get("html_url", ""),
        "commit_url": commit.get("html_url", ""),
        "updated": bool(sha),
    }
