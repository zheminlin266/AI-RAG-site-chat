"""Chat request validation, origin checks, rate limiting, and API helpers."""
from __future__ import annotations

import ipaddress
import time
from collections import defaultdict
from typing import TypedDict
from urllib.parse import urlsplit

import httpx
from fastapi import HTTPException, Request

from backend.config import (
    CORS_ORIGINS,
    MAX_CHARS,
    MAX_HISTORY,
    OPENROUTER_API_KEY,
    TRUSTED_PROXY_IPS,
)


class ChatMessage(TypedDict):
    role: str
    content: str


def _normalise_origin(value: str, *, allow_trailing_slash: bool = False) -> str | None:
    """Return a canonical web origin, or ``None`` for a malformed value."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None

    allowed_paths = {"", "/"} if allow_trailing_slash else {""}
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in allowed_paths
        or parsed.query
        or parsed.fragment
    ):
        return None

    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme}://{host}{port_suffix}"


def _request_origin(request: Request) -> str | None:
    host = request.headers.get("host", "")
    if not host:
        return None
    scheme = request.url.scheme
    # A TLS-terminating reverse proxy forwards HTTP to Uvicorn. Trust its
    # forwarded scheme only when its direct peer was explicitly configured;
    # otherwise an arbitrary client could turn http into https here.
    forwarded = request.headers.get("x-forwarded-proto", "")
    peer = request.client.host if request.client else ""
    if forwarded and _is_trusted_proxy(peer):
        candidate = forwarded.rsplit(",", 1)[-1].strip().lower()
        if candidate in {"http", "https"}:
            scheme = candidate
    return _normalise_origin(f"{scheme}://{host}")


def is_allowed_origin(request: Request, *, require_origin: bool = True) -> bool:
    """Allow only the exact request origin or an explicitly configured origin.

    ``Origin`` is a tuple of scheme, host, and port. Comparing hostname alone
    accidentally grants access across HTTP/HTTPS or development ports, so both
    configured CORS origins and the request Host header are canonicalised first.
    """
    raw_origin = request.headers.get("origin")
    if not raw_origin:
        return not require_origin

    origin = _normalise_origin(raw_origin)
    if origin is None:
        return False

    return origin == _request_origin(request) or origin in CORS_ORIGINS


def _is_trusted_proxy(peer: str) -> bool:
    if not TRUSTED_PROXY_IPS:
        return False
    try:
        address = ipaddress.ip_address(peer)
    except ValueError:
        return False
    return any(
        address in ipaddress.ip_network(value, strict=False)
        for value in TRUSTED_PROXY_IPS
    )


def client_ip(request: Request) -> str:
    """Return the peer IP, trusting X-Forwarded-For only from configured proxies."""
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded and _is_trusted_proxy(peer):
        # A trusted proxy appends its observed client address. Walk from the
        # right so an attacker-controlled leftmost value cannot bypass limits.
        for candidate in reversed(forwarded.split(",")):
            candidate = candidate.strip()
            try:
                return str(ipaddress.ip_address(candidate))
            except ValueError:
                continue
    return peer


# ponytail: This is process-local rate limiting. It is sufficient for one
# instance; use a shared store such as Redis when the service is scaled out.
_rate_store: dict[str, dict[str, list[float]]] = defaultdict(
    lambda: defaultdict(list)
)


def check_rate_limit(
    request: Request,
    bucket: str = "chat",
    max_req: int = 20,
    window_sec: int = 60,
) -> None:
    """Apply a small sliding-window rate limit to the caller's IP address."""
    ip = client_ip(request)
    now = time.monotonic()
    cutoff = now - window_sec
    bucket_store = _rate_store[bucket]

    # Remove expired entries for other clients too, so spoofed or one-off IPs
    # cannot make this in-memory limiter grow without bound.
    for stored_ip, timestamps in list(bucket_store.items()):
        timestamps[:] = [timestamp for timestamp in timestamps if timestamp > cutoff]
        if not timestamps:
            del bucket_store[stored_ip]

    entries = bucket_store[ip]
    if len(entries) >= max_req:
        raise HTTPException(
            status_code=429,
            detail="Too many requests. Please wait before trying again.",
        )
    entries.append(now)


def sanitize(raw: object) -> list[ChatMessage]:
    """Validate, truncate, and cap a user-supplied chat history."""
    if not isinstance(raw, list):
        return []

    cleaned: list[ChatMessage] = []
    for message in raw:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        content = message.get("content")
        if role not in {"user", "assistant"}:
            continue
        if not isinstance(content, str) or not content.strip():
            continue
        cleaned.append({"role": role, "content": content[:MAX_CHARS]})

    bounded = cleaned[-MAX_HISTORY:]
    # Keep complete turns: after a 40-message slice, the oldest item can be
    # the assistant half of a discarded turn. Drop it rather than sending an
    # orphan reply as context for the next user question.
    if bounded and bounded[0]["role"] == "assistant":
        bounded = bounded[1:]
    return bounded


def validate_last_user(messages: list[ChatMessage]) -> bool:
    return bool(messages) and messages[-1]["role"] == "user"


def get_openrouter_client() -> httpx.AsyncClient:
    """Create a short-lived client; callers must use it as an async context manager."""
    referer = CORS_ORIGINS[0] if CORS_ORIGINS else "http://localhost:8000"
    return httpx.AsyncClient(
        base_url="https://openrouter.ai/api/v1",
        headers={
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "HTTP-Referer": referer,
            "X-Title": "RAG Site Chat",
        },
        timeout=60.0,
    )


def friendly_error(err: Exception) -> str:
    """Convert upstream API errors to a safe, user-facing streaming message."""
    message = str(err).lower()
    status = getattr(err, "status_code", None) or getattr(err, "status", None)

    if status == 429 or ("rate" in message and "limit" in message):
        return "\n\n[I'm getting a lot of questions — give it a moment and try again.]"
    if status == 402 or any(
        word in message for word in ("credit", "quota", "insufficient", "payment")
    ):
        return "\n\n[The chat is out of credit at the moment. Try again later.]"
    if status == 404 or any(word in message for word in ("not found", "no endpoints")):
        return "\n\n[That model isn't available right now. Try again shortly.]"
    return "\n\n[Sorry — something went wrong. Try again in a moment.]"
