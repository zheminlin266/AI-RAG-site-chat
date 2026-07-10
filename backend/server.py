"""FastAPI endpoints for retrieval-augmented, streaming site chat."""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

import backend.config as cfg
from backend.chat_util import (
    ChatMessage,
    check_rate_limit,
    friendly_error,
    get_openrouter_client,
    is_allowed_origin,
    sanitize,
    validate_last_user,
)
from backend.config import (
    CORS_ORIGINS,
    GITHUB_CACHE_DIR,
    MAX_CONCURRENT_LLM,
    MAX_REQUEST_BODY_BYTES,
    MAX_TOKENS,
    OPENROUTER_API_KEY,
    PORT,
    RATE_LIMIT_CHAT,
    RATE_LIMIT_REBUILD,
    RATE_LIMIT_SUGGEST,
    RAW_DATA_DIR,
    REBUILD_SECRET,
    SUGGEST_MAX_TOKENS,
    SUGGEST_TEMPERATURE,
    TEMPERATURE,
    ensure_dirs,
    models,
)
from backend.github_source import clone_or_pull, is_github_url
from backend.persona import (
    SUGGEST_SYSTEM,
    build_suggest_prompt,
    build_system_prompt,
    parse_suggestions,
)
from backend.rag_engine import build_index, get_index_stats, search


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rag_site_chat")

_llm_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)
_rebuild_lock = asyncio.Lock()


async def _refresh_github_source() -> None:
    """Refresh a configured GitHub source before a startup build or rebuild."""
    if not RAW_DATA_DIR or not is_github_url(RAW_DATA_DIR):
        return

    GITHUB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    resolved = await asyncio.to_thread(clone_or_pull, RAW_DATA_DIR, GITHUB_CACHE_DIR)
    cfg.KNOWLEDGE_BASE_DIR = resolved
    logger.info("GitHub source resolved to: %s", resolved)


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()
    try:
        await _refresh_github_source()
    except Exception:
        logger.exception("GitHub source setup failed")
        raise

    logger.info("Knowledge base dir: %s", cfg.KNOWLEDGE_BASE_DIR)
    try:
        count = await asyncio.to_thread(build_index, force=False)
        logger.info("Index ready: %s chunks", count)
    except Exception as error:
        # The service can still start and report readiness/index status.
        logger.warning("Index build skipped: %s", error)
    yield


app = FastAPI(
    title="RAG Site Chat",
    description="RAG-powered AI chat module for static websites",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(CORS_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "X-Rebuild-Secret"],
    expose_headers=["X-RAG-Sources"],
)


async def _read_json_object(request: Request) -> dict:
    """Read at most 5 MiB of JSON without buffering an unbounded request body."""
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            declared_length = int(content_length)
        except ValueError as error:
            raise HTTPException(status_code=400, detail="Invalid Content-Length") from error
        if declared_length < 0:
            raise HTTPException(status_code=400, detail="Invalid Content-Length")
        if declared_length > MAX_REQUEST_BODY_BYTES:
            raise HTTPException(status_code=413, detail="Request body must not exceed 5 MiB")

    body = bytearray()
    try:
        async for chunk in request.stream():
            if len(chunk) > MAX_REQUEST_BODY_BYTES - len(body):
                raise HTTPException(status_code=413, detail="Request body must not exceed 5 MiB")
            body.extend(chunk)
    except HTTPException:
        raise
    except Exception as error:
        raise HTTPException(status_code=400, detail="Could not read request body") from error

    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HTTPException(status_code=400, detail="Invalid JSON") from error
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="JSON body must be an object")
    return payload


@app.get("/api/health")
async def health():
    stats = await asyncio.to_thread(get_index_stats)
    return {"status": "ok", "models": models(), **stats}


def _source_header(chunks: list[dict]) -> str:
    """Return a compact, display-safe list of retrieved source labels."""
    labels: list[str] = []
    for chunk in chunks:
        metadata = chunk.get("metadata", {})
        if not isinstance(metadata, dict):
            continue
        source = metadata.get("source", "")
        heading = metadata.get("heading", "")
        if not isinstance(source, str) or not source:
            continue
        label = f"{heading} — {source}" if isinstance(heading, str) and heading else source
        if label not in labels:
            labels.append(label[:240])
        if len(labels) == 3:
            break
    return json.dumps(labels, ensure_ascii=True, separators=(",", ":"))


@app.post("/api/rebuild-index")
async def rebuild_index(request: Request):
    """Safely rebuild the index when explicitly enabled and authenticated."""
    if not REBUILD_SECRET:
        # Do not expose an expensive administrative endpoint by default.
        raise HTTPException(status_code=404, detail="Not found")
    if not is_allowed_origin(request, require_origin=False):
        raise HTTPException(status_code=403, detail="Forbidden")

    provided_secret = request.headers.get("x-rebuild-secret", "")
    if not secrets.compare_digest(provided_secret, REBUILD_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")
    check_rate_limit(request, "rebuild", *RATE_LIMIT_REBUILD)

    if _rebuild_lock.locked():
        raise HTTPException(status_code=409, detail="An index rebuild is already in progress")

    async with _rebuild_lock:
        try:
            await _refresh_github_source()
            count = await asyncio.to_thread(build_index, force=True)
        except Exception:
            logger.exception("Index rebuild failed; the active index was retained")
            raise HTTPException(
                status_code=503,
                detail="Index rebuild failed; the existing index is still active.",
            )
    return {"status": "ok", "chunk_count": count}


@app.post("/api/chat")
async def chat(request: Request):
    """Stream a RAG-backed response as plain text."""
    if not is_allowed_origin(request):
        raise HTTPException(status_code=403, detail="Forbidden")
    check_rate_limit(request, "chat", *RATE_LIMIT_CHAT)

    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY is not set")

    body = await _read_json_object(request)
    messages = sanitize(body.get("messages"))
    if not validate_last_user(messages):
        raise HTTPException(status_code=400, detail="Last message must be from the user")

    query = messages[-1]["content"]
    try:
        retrieved_chunks = await asyncio.to_thread(search, query)
    except Exception:
        logger.exception("Retrieval failed")
        raise HTTPException(status_code=503, detail="Knowledge retrieval is temporarily unavailable")

    system_prompt = build_system_prompt(retrieved_chunks)
    api_messages: list[dict[str, str]] = [{"role": "system", "content": system_prompt}]
    api_messages.extend({"role": m["role"], "content": m["content"]} for m in messages)
    logger.info("Chat: chunks=%s, history_messages=%s", len(retrieved_chunks), len(messages))

    return StreamingResponse(
        _stream_chat(api_messages, request),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Accel-Buffering": "no",
            "X-RAG-Sources": _source_header(retrieved_chunks),
        },
    )


async def _stream_chat(
    messages: list[dict[str, str]],
    request: Request,
) -> AsyncGenerator[str, None]:
    """Run model fallback while closing the HTTP client on completion or disconnect."""
    try:
        await asyncio.wait_for(_llm_semaphore.acquire(), timeout=120)
    except asyncio.TimeoutError:
        yield "\n\n[The server is busy right now. Please try again in a moment.]"
        return

    try:
        async with get_openrouter_client() as client:
            produced = False
            last_error: Exception | None = None

            for model in models():
                if await request.is_disconnected():
                    return
                try:
                    async with client.stream(
                        "POST",
                        "/chat/completions",
                        json={
                            "model": model,
                            "messages": messages,
                            "temperature": TEMPERATURE,
                            "max_tokens": MAX_TOKENS,
                            "stream": True,
                        },
                    ) as response:
                        if response.status_code != 200:
                            error_body = (await response.aread()).decode(errors="replace")
                            raise _http_error(response.status_code, error_body)

                        async for line in response.aiter_lines():
                            if await request.is_disconnected():
                                return
                            if not line.startswith("data: "):
                                continue
                            data = line[6:]
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                                content = (
                                    chunk.get("choices", [{}])[0]
                                    .get("delta", {})
                                    .get("content", "")
                                )
                            except (json.JSONDecodeError, AttributeError, IndexError):
                                continue
                            if isinstance(content, str) and content:
                                produced = True
                                yield content
                    if produced:
                        return
                except Exception as error:
                    last_error = error
                    if produced:
                        yield friendly_error(error)
                        return
                    logger.warning("Model %s failed before output: %s", model, error)

            if last_error:
                yield friendly_error(last_error)
            else:
                yield "\n\n[No models available. Try again later.]"
    finally:
        _llm_semaphore.release()


def _http_error(status: int, body: str) -> Exception:
    error = Exception(body)
    error.status_code = status  # type: ignore[attr-defined]
    return error


@app.post("/api/suggest")
async def suggest(request: Request):
    """Generate short follow-up questions without retaining user history."""
    if not is_allowed_origin(request):
        raise HTTPException(status_code=403, detail="Forbidden")
    check_rate_limit(request, "suggest", *RATE_LIMIT_SUGGEST)
    if not OPENROUTER_API_KEY:
        return {"suggestions": []}

    body = await _read_json_object(request)
    messages: list[ChatMessage] = sanitize(body.get("messages"))
    if not messages or await request.is_disconnected():
        return {"suggestions": []}

    prompt = build_suggest_prompt(messages)
    async with _llm_semaphore:
        async with get_openrouter_client() as client:
            for model in models():
                try:
                    response = await client.post(
                        "/chat/completions",
                        json={
                            "model": model,
                            "messages": [
                                {"role": "system", "content": SUGGEST_SYSTEM},
                                {"role": "user", "content": prompt},
                            ],
                            "temperature": SUGGEST_TEMPERATURE,
                            "max_tokens": SUGGEST_MAX_TOKENS,
                        },
                    )
                    if response.status_code != 200:
                        continue
                    data = response.json()
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    suggestions = parse_suggestions(content)
                    if suggestions:
                        return {"suggestions": suggestions}
                except Exception:
                    continue
    return {"suggestions": []}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=PORT)
