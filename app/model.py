from __future__ import annotations

import base64
import json
import mimetypes
import re
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Any

from .config import LLM_API_KEY, LLM_BASE_URL, LLM_MODEL


class ModelNotConfigured(RuntimeError):
    pass


def configured() -> bool:
    if not LLM_MODEL:
        return False
    if LLM_API_KEY:
        return True
    # Allow unauthenticated OpenAI-compatible servers on loopback or a named local Docker service.
    parsed = urlparse(LLM_BASE_URL)
    return parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1", "host.docker.internal", "ollama"}


def chat(messages: list[dict[str, Any]], max_tokens: int = 1200) -> str:
    if not configured():
        raise ModelNotConfigured("未配置 LLM_API_KEY 或 LLM_MODEL")
    url = LLM_BASE_URL if LLM_BASE_URL.endswith("/chat/completions") else LLM_BASE_URL + "/chat/completions"
    payload = json.dumps({"model": LLM_MODEL, "messages": messages, "temperature": 0.2,
                          "max_tokens": max_tokens}).encode("utf-8")
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if LLM_API_KEY:
        headers["Authorization"] = f"Bearer {LLM_API_KEY}"
    req = urllib.request.Request(url, data=payload, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            data = json.loads(response.read().decode("utf-8"))
        return str(data["choices"][0]["message"]["content"]).strip()
    except urllib.error.HTTPError as exc:
        safe_body = exc.read(1000).decode("utf-8", errors="replace")
        raise RuntimeError(f"模型接口返回 HTTP {exc.code}: {safe_body}") from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"模型接口连接失败: {exc}") from exc


def summarize_text(title: str, text: str) -> str:
    if not configured():
        # Useful offline fallback: preserve a readable summary without pretending an LLM ran.
        cleaned = [part.strip() for part in text.replace("\r", "").split("\n\n") if part.strip()]
        paragraphs = [re.sub(r"\s+", " ", part) for part in cleaned if not part.lstrip().startswith("#")]
        lead = " ".join(paragraphs[:2])[:900] or text.strip()[:900]
        lines = [line.strip(" -*\t") for line in text.splitlines() if line.strip().startswith(("- ", "* ", "• "))]
        key_lines = lines[:5]
        result = ["本地初步摘要（未调用外部模型）：", lead or "（没有可提取的正文文字）"]
        if key_lines:
            result.append("\n核心要点：\n" + "\n".join(f"- {line[:300]}" for line in key_lines))
        return "\n\n".join(result)
    clipped = text[:24000]
    return chat([
        {"role": "system", "content": "你是个人知识库整理助手。使用中文，区分原文主张与推论，不要编造缺失信息。输出：一段摘要，然后 3-7 条核心要点。不要复述大段原文。"},
        {"role": "user", "content": f"资料标题：{title}\n\n请整理以下内容：\n{clipped}"},
    ], max_tokens=1300)


def extract_image_text_or_summary(path: Path) -> str:
    if not configured():
        return "（图片原件已保存，尚未识别文字。配置支持视觉输入的模型后可自动整理。）"
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return chat([
        {"role": "system", "content": "你是资料库图像转录助手。请先尽可能忠实提取图片中的文字，再给出简短摘要。无法辨认的部分标记为[无法辨认]，不要猜测。输出使用中文。"},
        {"role": "user", "content": [
            {"type": "text", "text": "请提取并整理这张图片。保留日期、截止时间、标题、来源等关键信息。"},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
        ]},
    ], max_tokens=1800)
