"""
RAG Site Chat — FastAPI server.

Endpoints:
  POST /api/chat        — Streaming chat with RAG retrieval
  POST /api/suggest     — Follow-up question suggestions
  GET  /api/health      — Health check + index status
  POST /api/rebuild-index — Force rebuild knowledge index

Start:
  python -m backend.server
  uvicorn backend.server:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from backend.chat_util import (
    ChatMessage,
    check_rate_limit,
    friendly_error,
    get_openrouter_client,
    is_allowed_origin,
    sanitize,
    sanitize_output,
    session_id_of,
    validate_last_user,
)
from backend.config import (
    CORS_ORIGIN,
    GITHUB_CACHE_DIR,
    KNOWLEDGE_BASE_DIR,
    MAX_CONCURRENT_LLM,
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
from backend.persona import (
    SUGGEST_SYSTEM,
    build_suggest_prompt,
    build_system_prompt,
    parse_suggestions,
)
from backend.rag_engine import build_index, get_index_stats, search

# ── 日志 ────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("rag_site_chat")

# ── 并发控制 ────────────────────────────────────────

_llm_semaphore = asyncio.Semaphore(MAX_CONCURRENT_LLM)

# ── 启动/关闭 ───────────────────────────────────────


@asynccontextmanager
async def lifespan(app: FastAPI):
    ensure_dirs()

    # 处理 GitHub 数据源
    from backend.github_source import clone_or_pull, is_github_url
    import backend.config as cfg

    if RAW_DATA_DIR and is_github_url(RAW_DATA_DIR):
        logger.info(f"GitHub data source detected: {RAW_DATA_DIR}")
        GITHUB_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            resolved = clone_or_pull(RAW_DATA_DIR, GITHUB_CACHE_DIR)
            cfg.KNOWLEDGE_BASE_DIR = resolved
            logger.info(f"GitHub source resolved to: {resolved}")
        except Exception as e:
            logger.error(f"GitHub source setup failed: {e}")
            raise

    logger.info(f"Knowledge base dir: {cfg.KNOWLEDGE_BASE_DIR}")
    logger.info("Building knowledge base index...")
    try:
        count = build_index(force=False)
        logger.info(f"Index ready: {count} chunks")
    except Exception as e:
        logger.warning(f"Index build skipped: {e}")
    yield


app = FastAPI(
    title="RAG Site Chat",
    description="RAG-powered AI chat module for any static website",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGIN.split(",") if CORS_ORIGIN != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── 健康检查 ─────────────────────────────────────────


@app.get("/api/health")
async def health():
    stats = get_index_stats()
    return {
        "status": "ok",
        "has_index": stats["has_index"],
        "chunk_count": stats["chunk_count"],
    }


# ── 重建索引 ─────────────────────────────────────────


@app.post("/api/rebuild-index")
async def rebuild_index(request: Request):
    # 频率限制
    check_rate_limit(request, "rebuild", RATE_LIMIT_REBUILD[0], RATE_LIMIT_REBUILD[1])

    # 简单密钥保护（生产环境建议用 nginx basic auth）
    if REBUILD_SECRET:
        provided = request.headers.get("x-rebuild-secret", "")
        if provided != REBUILD_SECRET:
            raise HTTPException(status_code=403, detail="Forbidden")

    try:
        count = build_index(force=True)
        return {"status": "ok", "chunk_count": count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 聊天 ─────────────────────────────────────────────


@app.post("/api/chat")
async def chat(request: Request):
    """
    Streaming chat endpoint.

    Request: { messages: [{role, content}], sessionId?: string }
    Response: text/plain stream, one token per chunk.
    """
    if not is_allowed_origin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    check_rate_limit(request, "chat", RATE_LIMIT_CHAT[0], RATE_LIMIT_CHAT[1])

    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY is not set")

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    messages = sanitize(body.get("messages"))
    if not validate_last_user(messages):
        raise HTTPException(status_code=400, detail="Last message must be from the user")

    query = messages[-1]["content"]
    retrieved_chunks = search(query)
    system_prompt = build_system_prompt(retrieved_chunks)

    api_messages: list[dict] = [{"role": "system", "content": system_prompt}]
    for m in messages:
        api_messages.append({"role": m["role"], "content": m["content"]})

    logger.info(
        f"Chat: query='{query[:80]}...', chunks={len(retrieved_chunks)}, "
        f"history={len(messages)}"
    )

    return StreamingResponse(
        _stream_chat(api_messages, request),
        media_type="text/plain; charset=utf-8",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Accel-Buffering": "no",
        },
    )


async def _stream_chat(
    messages: list[dict],
    request: Request,
) -> AsyncGenerator[str, None]:
    """Stream LLM response with model fallback, concurrency limit, and output sanitization."""
    # 并发控制：获取信号量，超时 120 秒自动释放
    try:
        acquired = await asyncio.wait_for(_llm_semaphore.acquire(), timeout=120)
    except asyncio.TimeoutError:
        yield "\n\n[The server is busy right now. Please try again in a moment.]"
        return

    try:
        client = get_openrouter_client()
        model_list = models()
        last_error: Exception | None = None
        produced = False

        async def try_model(model: str) -> AsyncGenerator[str, None]:
            nonlocal produced
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
                    body = await response.aread()
                    raise _http_error(response.status_code, body.decode())

                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            produced = True
                            yield sanitize_output(content)
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue

        for model in model_list:
            try:
                async for token in try_model(model):
                    yield token
                if produced:
                    return
            except Exception as e:
                last_error = e
                if produced:
                    yield friendly_error(e)
                    return
                logger.warning(f"Model {model} failed (no output): {e}")

        if last_error:
            yield friendly_error(last_error)
        else:
            yield "\n\n[No models available. Try again later.]"
    finally:
        _llm_semaphore.release()


def _http_error(status: int, body: str) -> Exception:
    err = Exception(body)
    err.status_code = status  # type: ignore[attr-defined]
    return err


# ── 追问建议 ─────────────────────────────────────────


@app.post("/api/suggest")
async def suggest(request: Request):
    """
    Follow-up question suggestions.

    Request: { messages: [...], sessionId?: string }
    Response: { suggestions: string[] }
    """
    if not is_allowed_origin(request):
        raise HTTPException(status_code=403, detail="Forbidden")

    check_rate_limit(request, "suggest", RATE_LIMIT_SUGGEST[0], RATE_LIMIT_SUGGEST[1])

    if not OPENROUTER_API_KEY:
        return {"suggestions": []}

    try:
        body = await request.json()
    except Exception:
        return {"suggestions": []}

    messages = sanitize(body.get("messages"))
    if not messages:
        return {"suggestions": []}

    prompt = build_suggest_prompt(messages)
    model_list = models()

    async with _llm_semaphore:
        client = get_openrouter_client()
        for model in model_list:
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
                if response.status_code == 200:
                    data = response.json()
                    text = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    suggestions = parse_suggestions(text)
                    if suggestions:
                        return {"suggestions": suggestions}
            except Exception:
                continue

    return {"suggestions": []}


# ── 启动入口 ─────────────────────────────────────────


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=PORT)
