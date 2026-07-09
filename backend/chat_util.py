"""
Chat utility functions — Origin validation, message sanitization, HTTP client,
rate limiting, and output safety.
"""
from __future__ import annotations

import re
import time
from collections import defaultdict
from typing import TypedDict
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException, Request

from backend.config import MAX_HISTORY, MAX_CHARS, CORS_ORIGIN, OPENROUTER_API_KEY

# ── 类型 ────────────────────────────────────────────


class ChatMessage(TypedDict):
    role: str
    content: str


# ── Origin 校验 ─────────────────────────────────────


def is_allowed_origin(request: Request) -> bool:
    """
    Lightweight abuse protection: only serve same-origin browser requests.
    Accepts matching hosts, localhost, and configured CORS origins.
    """
    origin = request.headers.get("origin")
    if not origin:
        return False

    try:
        origin_host = urlparse(origin).hostname
    except Exception:
        return False

    if origin_host is None:
        return False

    if origin_host in ("localhost", "127.0.0.1", "::1"):
        return True

    host = request.headers.get("host", "")
    allowed = {host}
    if CORS_ORIGIN and CORS_ORIGIN != "*":
        for u in CORS_ORIGIN.split(","):
            try:
                h = urlparse(u.strip()).hostname
                if h:
                    allowed.add(h)
            except Exception:
                pass

    return origin_host in allowed


def client_ip(request: Request) -> str:
    """Extract client IP, respecting X-Forwarded-For behind reverse proxy."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    host = request.client.host if request.client else "unknown"
    return host


# ═══════════════════════════════════════════════════════
# 频率限制（滑动窗口，进程内内存存储）
#
# ponytail: 单进程内存计数，重启后丢失。对个人站点足够。
# 多进程部署需改用 Redis 或共享存储。
# ═══════════════════════════════════════════════════════

_rate_store: dict[str, dict[str, list[float]]] = defaultdict(
    lambda: defaultdict(list)
)


def check_rate_limit(
    request: Request,
    bucket: str = "chat",
    max_req: int = 20,
    window_sec: int = 60,
) -> None:
    """
    Sliding-window rate limit per client IP.
    Raises HTTPException(429) if limit exceeded.

    bucket: logical grouping (e.g. "chat", "suggest", "rebuild")
    max_req: max requests in the window
    window_sec: window size in seconds
    """
    ip = client_ip(request)
    now = time.time()
    cutoff = now - window_sec

    entries = _rate_store[bucket][ip]
    entries[:] = [t for t in entries if t > cutoff]

    if len(entries) >= max_req:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before trying again.",
        )

    entries.append(now)


# ═══════════════════════════════════════════════════════
# 输出安全：防 HTML/URL 注入
#
# 前端用 whitespace-pre-wrap 渲染纯文本，HTML 标签不会被浏览器解析。
# 但 <img src=...> 会触发外部请求（tracking pixel），所以服务端也做一层清理。
# ═══════════════════════════════════════════════════════

_HTML_TAG_RE = re.compile(r"<[^>]*>")
_URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)


def sanitize_output(text: str) -> str:
    """Strip HTML tags and replace URLs with placeholder."""
    text = _HTML_TAG_RE.sub("", text)
    text = _URL_RE.sub("[link removed]", text)
    return text


# ── 消息净化 ────────────────────────────────────────


def sanitize(raw: object) -> list[ChatMessage]:
    """Validate and clean message array: filter, truncate, cap history."""
    if not isinstance(raw, list):
        return []

    cleaned: list[ChatMessage] = []
    for m in raw:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content")
        if role not in ("user", "assistant"):
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        cleaned.append(ChatMessage(role=str(role), content=content[:MAX_CHARS]))

    return cleaned[-MAX_HISTORY:]


def validate_last_user(messages: list[ChatMessage]) -> bool:
    return len(messages) > 0 and messages[-1]["role"] == "user"


# ── OpenRouter 客户端 ────────────────────────────────


def get_openrouter_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": CORS_ORIGIN if CORS_ORIGIN != "*" else "http://localhost:8000",
            "X-Title": "RAG Site Chat",
        },
        timeout=60.0,
    )


# ── 错误处理 ────────────────────────────────────────


def friendly_error(err: Exception) -> str:
    """Convert API errors to user-friendly messages."""
    msg = str(err).lower()
    status = getattr(err, "status_code", None) or getattr(err, "status", None)

    if status == 429 or ("rate" in msg and "limit" in msg):
        return "\n\n[I'm getting a lot of questions — give it a moment and try again.]"
    if status == 402 or any(w in msg for w in ("credit", "quota", "insufficient", "payment")):
        return "\n\n[The chat is out of credit at the moment. Try again later.]"
    if status == 404 or any(w in msg for w in ("not found", "no endpoints")):
        return "\n\n[That model isn't available right now. Try again shortly.]"

    return "\n\n[Sorry — something went wrong. Try again in a moment.]"


# ── Session ID ──────────────────────────────────────


def session_id_of(raw: object) -> str | None:
    if isinstance(raw, str) and raw.strip():
        return raw.strip()[:200]
    return None
