# RAG Instruction — AI-RAG-site-chat

> **English** below | **中文翻译** 见后半部分

---

## Table of Contents | 目录

1. [Overview](#1-overview)
2. [RAG Pipeline Architecture](#2-rag-pipeline-architecture)
3. [Data Sources](#3-data-sources)
4. [Document Loading & Parsing](#4-document-loading--parsing)
5. [Chunking Strategy](#5-chunking-strategy)
6. [Embedding Generation](#6-embedding-generation)
7. [Vector Storage](#7-vector-storage)
8. [Hybrid Retrieval](#8-hybrid-retrieval)
9. [Prompt Construction & Guardrails](#9-prompt-construction--guardrails)
10. [Configuration Reference](#10-configuration-reference)
11. [API Endpoints (RAG-Related)](#11-api-endpoints-rag-related)
12. [Design Decisions & Rationale](#12-design-decisions--rationale)

---

## 1. Overview

**AI-RAG-site-chat** is a lightweight, self-contained Retrieval-Augmented Generation (RAG) chatbot that can be embedded into any website. It answers user questions exclusively from a configured knowledge base — a set of documents (Markdown, HTML, JSON, plain text) stored locally or in a GitHub repository.

### Core Principles

| Principle | Implementation |
|-----------|---------------|
| **Source-grounded** | All answers must cite knowledge base content; fabrication is explicitly prohibited by guardrail prompts |
| **Zero local model download** | Embeddings and LLM inference are both served via OpenRouter API |
| **Hybrid retrieval** | Vector similarity + BM25 keyword search, fused via Reciprocal Rank Fusion (RRF) |
| **Single-process simplicity** | No external database, no message queue, no microservices — one FastAPI process does everything |
| **Pluggable persona** | AI identity, tone, and domain expertise defined in an editable `PERSONA.md` file |

### Tech Stack at a Glance

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI + uvicorn (Python 3.11+) |
| Vector Store | ChromaDB (persistent, HNSW index, cosine distance) |
| Keyword Search | rank-bm25 (BM25Okapi) |
| Embedding Model | `openai/text-embedding-3-small` (1536-dim) via OpenRouter |
| LLM | `deepseek/deepseek-v4-flash` (primary), `google/gemini-2.0-flash-001` (fallback) via OpenRouter |
| Frontend | React 18 + TypeScript + Tailwind CSS + framer-motion |
| Deployment | Docker + docker-compose, GitHub Actions CI/CD to ghcr.io |

---

## 2. RAG Pipeline Architecture

The pipeline has two phases: **Indexing** (offline/boot) and **Retrieval** (online/per-query).

```
┌─────────────────────────────────────────────────────────┐
│                     INDEXING PHASE                       │
│                                                         │
│  DATA_DIR ──► Loaders ──► Documents ──► Chunking        │
│  (files or   (md/html/   [{path,      (heading-aware    │
│   GitHub)     json/txt)   content}]    recursive split)  │
│                                            │             │
│                    ┌───────────────────────┘             │
│                    ▼                                     │
│              Chunks [{id, text, source, heading}]        │
│                    │                                     │
│         ┌──────────┴──────────┐                          │
│         ▼                     ▼                          │
│   Embedding API         Tokenize + BM25                  │
│   (batch size=50)       (build corpus index)             │
│         │                     │                          │
│         ▼                     ▼                          │
│   ChromaDB               In-memory                       │
│   (cosine HNSW)          BM25Okapi index                 │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    RETRIEVAL PHASE                        │
│                                                         │
│  User Query "What is copper exploration?"               │
│         │                                                │
│    ┌────┴────┐                                          │
│    ▼         ▼                                          │
│  Embed     Tokenize                                      │
│  Query     Query                                         │
│    │         │                                           │
│    ▼         ▼                                           │
│  ChromaDB  BM25                                          │
│  Top-50   Top-50                                         │
│  (cosine  (keyword                                       │
│   filter   scores)                                       │
│   ≥0.5)                                                  │
│    │         │                                           │
│    └────┬────┘                                           │
│         ▼                                                │
│    RRF Fusion                                            │
│    score = Σ 1/(60+rank)                                │
│         │                                                │
│         ▼                                                │
│    Top-20 Chunks ──► System Prompt ──► LLM ──► Answer   │
└─────────────────────────────────────────────────────────┘
```

---

## 3. Data Sources

Three mutually exclusive modes, resolved in order:

| Priority | Source | Config | Mechanism |
|----------|--------|--------|-----------|
| 1 | **Local directory** | `DATA_DIR=/path/to/docs` | Direct filesystem scan, recursive |
| 2 | **GitHub repository** | `DATA_DIR=https://github.com/user/repo` | Sparse clone (depth-1, blobless) → `git pull --ff-only` on rebuild |
| 3 | **Default directory** | (none set) | Falls back to `knowledge-base/` |

### GitHub Source Behavior

- **First time**: `git clone --depth 1 --filter=blob:none --sparse <url>` into `.github_cache/`
- **Subsequent rebuilds**: `git pull --ff-only` for incremental updates
- **Cache directory**: `.github_cache/` (persisted via Docker named volume `github_cache`)
- The sparse checkout is then scanned like a local directory through the same loader pipeline.

---

## 4. Document Loading & Parsing

All loaders reside in `backend/parsers/`. Each returns `[{path: str, content: str}]`.

### 4.1 Markdown Loader (`md_loader.py`)
- Reads `.md` files as-is, preserving original Markdown formatting.
- The raw Markdown is intentionally kept — LLMs understand Markdown syntax natively.

### 4.2 HTML Loader (`html_loader.py`)
- Uses BeautifulSoup to extract semantic content.
- **Priority extraction order**:
  1. `<article>`, `<section>`, `<main>` — retain heading hierarchy (h1-h4)
  2. Fallback to paragraph structure (`<p>`, `<li>`)
  3. Final fallback to `.get_text()` plain text
- Strips `<script>`, `<style>`, `<nav>`, `<footer>` before extraction.

### 4.3 JSON Loader (`json_loader.py`)
- Flattens structured JSON into narrative text.
- **Arrays**: each element becomes a separate entry with index label ("Item 1: ...").
- **Objects**: key-value pairs are rendered as named paragraphs. Recognizes semantic keys: `title`, `content`, `summary`, `date`, `source`, `tags`.
- **Nested structures**: recursively flattened.

### 4.4 Text Loader (`txt_loader.py`)
- Reads `.txt` files directly as UTF-8 text.

### Scanning Rules
- Recursively walks all subdirectories.
- **Skips**: hidden directories/files (names starting with `.`), ChromaDB internal files.
- No file count or size limits — bounded only by available memory.

---

## 5. Chunking Strategy

A **three-stage, heading-aware recursive split** implemented in `rag_engine.py`.

### Stage 1: Split by Markdown Headings (`_split_by_headings`)
```
Document
  ├── # Heading 1  ──► Section (heading="Heading 1")
  │     Content under H1...
  ├── ## Heading 2  ──► Section (heading="Heading 1 > Heading 2")
  │     Content under H2...
  └── ### Heading 3 ──► Section (heading="Heading 1 > Heading 2 > Heading 3")
        Content under H3...
```
- Each heading level creates a separate section.
- Heading breadcrumbs are preserved as metadata for source citation.

### Stage 2: Split Long Sections by Sentences (`_split_long_section`)
- If a section's estimated token count exceeds `CHUNK_SIZE` (default: 500), split by sentences.
- **Sentence delimiters**: `。！？.!?\n`
- Sliding window with overlap (`CHUNK_OVERLAP`, default: 50 tokens) to preserve cross-chunk context.

### Stage 3: Token Estimation (`_estimate_tokens`)
```
estimated_tokens = len(Chinese_chars) / 1.5 + len(Latin_digits) / 4
```
- This is a heuristic approximation, not a real tokenizer.
- **ponytail: O(n) scan; max error ~30% for mixed CJK/Latin text. Upgradable to tiktoken for exact counts.**

### Chunk ID Generation (`_make_chunk_id`)
```
chunk_id = MD5(source_path | heading_path | text_content)[:16]
```
- **Stable**: same content produces same ID across rebuilds.
- **Deterministic**: no randomness, no timestamp dependency.
- Enables deduplication — if a document hasn't changed, its chunks retain the same IDs.

### Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `CHUNK_SIZE` | 500 | Max tokens per chunk (estimated) |
| `CHUNK_OVERLAP` | 50 | Token overlap between adjacent chunks |

---

## 6. Embedding Generation

### Model
- **Default**: `openai/text-embedding-3-small` (1536-dimensional vectors)
- **Alternatives** (configurable via `EMBEDDING_MODEL`):
  - `google/text-embedding-004` (768-dim, $0.0025/1M tokens)
  - `cohere/embed-multilingual-v3.0` (1024-dim, $0.10/1M tokens)

### API Call
```
POST https://openrouter.ai/api/v1/embeddings
Headers:
  Authorization: Bearer <OPENROUTER_API_KEY>
Body:
  {
    "model": "openai/text-embedding-3-small",
    "input": ["text chunk 1", "text chunk 2", ...]
  }
```

### Batching
- **Indexing**: chunks are embedded in batches of 50 (`_embed_in_batches()`).
- **Query**: single query embedding, no batching needed.
- Timeout: 120 seconds per API call.

### Dimensionality Note
Different embedding models produce vectors of different dimensions. ChromaDB auto-detects dimensionality on first insert. Changing `EMBEDDING_MODEL` after initial indexing requires a **full rebuild** (`POST /api/rebuild-index`).

---

## 7. Vector Storage

### ChromaDB Configuration
```python
chromadb.PersistentClient(path=".chroma_db/")
collection = get_or_create_collection(
    name="knowledge",
    metadata={"hnsw:space": "cosine"}
)
```

| Property | Value |
|----------|-------|
| **Storage** | Persistent, local filesystem (`.chroma_db/`) |
| **Index** | HNSW (Hierarchical Navigable Small World) |
| **Distance metric** | Cosine distance |
| **Collection** | Single collection named `knowledge` |
| **Metadata per chunk** | `{source: filepath, heading: heading_path}` |

### Persistence
- **Local**: `.chroma_db/` directory in project root.
- **Docker**: Docker named volume `chroma_data` mounted at `/app/.chroma_db`.
- Survives container restarts. Not shared across instances (single-server design).

### Consistency Guarantee
- BM25 index and ChromaDB are rebuilt together atomically at startup and on manual rebuild.
- No incremental update — the entire index is rebuilt from scratch each time.
- **ponytail: O(N) rebuild on every change. Acceptable for knowledge bases under ~10K documents. For larger bases, consider incremental indexing with document hash tracking.**

---

## 8. Hybrid Retrieval

This is the core retrieval strategy. It combines **semantic search** (vector) and **keyword search** (BM25) to maximize recall for both conceptual queries and exact terminology matches.

### 8.1 Vector Search (Semantic)

```
1. Embed user query → 1536-dim vector
2. ChromaDB.query(query_embeddings=[vector], n_results=CANDIDATE_K)
3. Filter: keep only chunks where cosine distance > MIN_SIMILARITY (default: 0.5)
4. Result: vector_ranked = [(chunk_id, distance), ...]
```

- `MIN_SIMILARITY` acts as a relevance gate — chunks below the threshold are discarded.
- Set `MIN_SIMILARITY=1.0` to disable filtering (accept all candidates).
- Lower values (e.g., 0.3) are more permissive; higher values (e.g., 0.7) more strict.

### 8.2 BM25 Keyword Search (Lexical)

```
1. Tokenize user query (Chinese: char unigram + bigram; English: whitespace split)
2. BM25Okapi.get_scores(tokenized_query)
3. Take top CANDIDATE_K results
4. Result: bm25_ranked = [(chunk_id, score), ...]
```

#### Tokenizer Design (`_tokenize`)

Designed for **Chinese-English mixed text** with zero external NLP dependencies:

| Language | Strategy | Example |
|----------|----------|---------|
| Chinese | Character unigram + bigram | "铜矿" → `["铜", "铜矿", "矿"]` |
| English | Whitespace split, lowercased, punctuation stripped | "Copper Mining" → `["copper", "mining"]` |
| Numbers | Treated as English tokens | "2024产量" → `["2024", "产", "产量", "量"]` |

**ponytail: bigram approach handles most Chinese compound words but misses 3+ character compounds like "锂电池". Upgrade path: integrate jieba with custom dictionary for domain terminology.**

### 8.3 RRF Fusion (Reciprocal Rank Fusion)

```
For each unique chunk across both result sets:
  rrf_score = Σ 1 / (60 + rank_in_list)
```

- `k=60` is the standard RRF constant recommended by the original paper.
- Chunks appearing in both result sets get boosted (sum of both ranks).
- Final output: top `RETRIEVAL_K` (default: 20) chunks sorted by RRF score.

**Why RRF instead of LLM re-ranking?**
- RRF is **zero-cost** (no additional API call).
- RRF is **deterministic** (no LLM randomness or hallucination risk in retrieval).
- In practice, the combination of vector + BM25 already provides strong precision; LLM re-ranking adds latency and cost with marginal gain.

### 8.4 Configuration Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `RETRIEVAL_K` | 20 | Final number of chunks passed to LLM |
| `RETRIEVAL_CANDIDATE_K` | 50 | Candidates from each search method |
| `MIN_SIMILARITY` | 0.5 | Cosine distance threshold (lower = stricter) |

---

## 9. Prompt Construction & Guardrails

### 9.1 System Prompt Structure

The final system prompt is a **four-layer assembly** built in `persona.py`:

```
┌──────────────────────────────────────────┐
│ LAYER 1: PERSONA                         │
│ Content of PERSONA.md                    │
│ → AI identity, tone, domain expertise    │
├──────────────────────────────────────────┤
│ LAYER 2: KNOWLEDGE CONTEXT               │
│ Formatted retrieved chunks:              │
│                                          │
│ [Source: report.md] — Copper Analysis   │
│ Copper exploration in Chile continues... │
│ ---                                      │
│ [Source: data.json] — Gold Prices        │
│ Gold prices fluctuated this week...      │
├──────────────────────────────────────────┤
│ LAYER 3: CITING RULES                    │
│ "Always cite the source file and        │
│  heading when referencing information."  │
├──────────────────────────────────────────┤
│ LAYER 4: GUARDRAILS                      │
│ 1. SOURCE GROUNDING                      │
│ 2. STAY IN CHARACTER                     │
│ 3. SCOPE BOUNDARY                        │
│ 4. RESPONSE FORMAT                       │
│ 5. RESPONSE LENGTH                       │
└──────────────────────────────────────────┘
```

### 9.2 Guardrail Details

| # | Rule | Description |
|---|------|-------------|
| 1 | **SOURCE GROUNDING** | Only use information from the knowledge base. If the answer isn't in the provided context, say so. Never fabricate. |
| 2 | **STAY IN CHARACTER** | Maintain the persona defined in PERSONA.md. Do not break the fourth wall or acknowledge being an AI. |
| 3 | **SCOPE BOUNDARY** | Politely decline requests outside the persona's domain. Redirect to the defined topic area. |
| 4 | **RESPONSE FORMAT** | Plain text only. No HTML, no Markdown formatting in final output (knowledge context is formatted for LLM comprehension, not user display). |
| 5 | **RESPONSE LENGTH** | Default 2-4 sentences. Be concise. Expand only when the question demands detail. |

### 9.3 Persona File (`PERSONA.md`)

- Editable Markdown file defining AI behavior, expertise, and tone.
- **Hot-reloadable**: edit the file on disk; changes take effect on the next request (no restart needed).
- Docker: bind-mounted at `/app/PERSONA.md` (read-only).

### 9.4 Chunk Formatting (`_format_chunks`)

Each chunk in the knowledge context is formatted as:
```
[Source: relative/path/to/file.md] — Section Heading
Chunk text content here...
---
```
- Source path is relative to `DATA_DIR` root.
- Section heading shows the breadcrumb path (e.g., "Chapter 1 > Section 2").
- Separator `---` between chunks for visual clarity.

---

## 10. Configuration Reference

All parameters are read from environment variables (`.env` file or Docker env). See `.env.example` for the complete template.

### 10.1 Required

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_API_KEY` | *(required)* | OpenRouter API key for embeddings + LLM |

### 10.2 Data Source

| Variable | Default | Description |
|----------|---------|-------------|
| `DATA_DIR` | *(empty)* | Path to local docs or GitHub URL. Falls back to `knowledge-base/` |
| `KNOWLEDGE_BASE_DIR` | `knowledge-base/` | Alternative fallback directory |
| `PERSONA_FILE` | `PERSONA.md` | Path to persona definition file |
| `GITHUB_CACHE_DIR` | `.github_cache/` | Cache directory for GitHub sparse clones |

### 10.3 RAG Parameters

| Variable | Default | Range | Description |
|----------|---------|-------|-------------|
| `EMBEDDING_MODEL` | `openai/text-embedding-3-small` | Any OpenRouter embedding model | Embedding model ID |
| `CHUNK_SIZE` | `500` | 100-2000 | Max estimated tokens per chunk |
| `CHUNK_OVERLAP` | `50` | 0-500 | Token overlap between chunks |
| `RETRIEVAL_K` | `20` | 1-100 | Chunks passed to LLM |
| `RETRIEVAL_CANDIDATE_K` | `50` | 10-500 | Candidates per search method |
| `MIN_SIMILARITY` | `0.5` | 0.0-2.0 | Cosine distance threshold for vector search |

### 10.4 LLM Parameters

| Variable | Default | Description |
|----------|---------|-------------|
| `OPENROUTER_MODEL` | `deepseek/deepseek-v4-flash,google/gemini-2.0-flash-001` | Comma-separated model list (fallback chain) |
| `MAX_TOKENS` | `1024` | Max output tokens per chat response |
| `TEMPERATURE` | `0.6` | LLM temperature for chat |
| `SUGGEST_MAX_TOKENS` | `200` | Max tokens for follow-up suggestions |
| `SUGGEST_TEMPERATURE` | `0.7` | LLM temperature for suggestions |
| `MAX_HISTORY` | `20` | Max conversation turns kept in context |
| `MAX_CHARS` | `4000` | Max characters per single message |
| `MAX_CONCURRENT_LLM` | `5` | Max concurrent LLM API calls |

### 10.5 Security & Service

| Variable | Default | Description |
|----------|---------|-------------|
| `CORS_ORIGIN` | `*` | Comma-separated allowed origins |
| `RATE_LIMIT_CHAT_MAX` | `20` | Chat requests per window |
| `RATE_LIMIT_CHAT_WINDOW` | `60` | Chat rate limit window (seconds) |
| `RATE_LIMIT_SUGGEST_MAX` | `30` | Suggest requests per window |
| `RATE_LIMIT_SUGGEST_WINDOW` | `60` | Suggest rate limit window (seconds) |
| `RATE_LIMIT_REBUILD_MAX` | `3` | Rebuild requests per window |
| `RATE_LIMIT_REBUILD_WINDOW` | `300` | Rebuild rate limit window (seconds) |
| `REBUILD_SECRET` | *(empty = disabled)* | Secret for `/api/rebuild-index` protection |
| `PORT` | `8000` | HTTP server port |

---

## 11. API Endpoints (RAG-Related)

### 11.1 GET `/api/health`

Returns index status. No authentication required.

**Response:**
```json
{
  "status": "ok",
  "has_index": true,
  "chunk_count": 42,
  "has_bm25": true,
  "retrieval_k": 20,
  "candidate_k": 50,
  "min_similarity": 0.5
}
```

### 11.2 POST `/api/chat`

Main chat endpoint with RAG retrieval.

**Request:**
```json
{
  "messages": [
    {"role": "user", "content": "What is the current state of copper exploration?"}
  ],
  "sessionId": "optional-session-id"
}
```

**Response:** `text/plain` streaming — each chunk is a raw text token from the LLM.

**Processing flow:**
1. Origin validation (CORS)
2. Rate limit check (sliding window, per IP, 20 req/min default)
3. Message sanitization (role filtering, length truncation, history limit)
4. RAG retrieval (hybrid search → RRF fusion → top-K chunks)
5. System prompt assembly (persona + chunks + guardrails)
6. Streaming LLM call with automatic model failover
7. Output sanitization (HTML tag/URL stripping)

### 11.3 POST `/api/suggest`

Generates 3 contextual follow-up questions. Does NOT perform RAG retrieval — purely conversation-context based.

### 11.4 POST `/api/rebuild-index`

Force-rebuilds the entire knowledge base index. Optionally protected by `REBUILD_SECRET` via `x-rebuild-secret` header.

**Processing:**
1. Re-scan data source (local files or `git pull` for GitHub)
2. Re-parse all documents
3. Re-chunk with current `CHUNK_SIZE`/`CHUNK_OVERLAP` settings
4. Re-embed all chunks and rebuild ChromaDB collection
5. Rebuild BM25 index

### Rate Limiting

| Endpoint | Default Limit |
|----------|---------------|
| `/api/chat` | 20 requests / 60 seconds |
| `/api/suggest` | 30 requests / 60 seconds |
| `/api/rebuild-index` | 3 requests / 300 seconds |

Rate limiting uses a **sliding window** algorithm keyed by client IP. All limits are configurable via environment variables.

---

## 12. Design Decisions & Rationale

### 12.1 Why Hybrid Retrieval (Not Pure Vector Search)?

Vector search excels at semantic similarity but struggles with:
- **Exact terminology** (e.g., "ROE 15.3%", product codes, legal clause numbers)
- **Rare domain terms** that may not be well-represented in embedding training data
- **Negations and precise conditions** ("NOT copper", "before 2023")

BM25 fills these gaps by matching literal tokens. RRF fusion combines both without the latency and cost of LLM re-ranking.

### 12.2 Why No LLM Re-ranking?

- **Latency**: Each additional LLM call adds 500ms-2s.
- **Cost**: Re-ranking N candidates costs approximately (N × avg_chunk_tokens) input tokens.
- **Diminishing returns**: In testing, the precision gain from LLM re-ranking over RRF is marginal (<5%) for this use case.
- **Determinism**: RRF is reproducible; LLM re-ranking is stochastic.

### 12.3 Why Single-Process Architecture?

- **Simplicity**: No Redis, no PostgreSQL, no message queue. One `docker-compose up` deploys everything.
- **Sufficiency**: For knowledge bases under ~10K documents and moderate traffic, a single process with in-memory BM25 and local ChromaDB is more than adequate.
- **Trade-off**: Not horizontally scalable. For multi-instance deployments, ChromaDB and BM25 would need externalization.

### 12.4 Why No External NLP Dependencies?

The tokenizer uses character-level unigram+bigram for Chinese and whitespace splitting for English — no jieba, no spaCy, no NLTK. This keeps the Docker image small (~200MB) and avoids version conflicts.

**Known limitation**: 3+ character Chinese compounds ("锂电池", "人工智能") may not be matched as single tokens. For domain-specific knowledge bases, consider adding a custom dictionary or integrating jieba.

### 12.5 Why Cosine Distance ≥ 0.5?

After empirical testing, chunks with cosine distance below 0.5 from the query vector were consistently irrelevant. This threshold acts as a **quality gate** — it prevents the LLM from receiving noise that could trigger hallucinations. Adjust per domain: stricter for factual/technical content (0.3-0.4), looser for creative/open-ended content (0.6-0.7).

### 12.6 Why Stable Chunk IDs?

Chunk IDs are MD5 hashes of `(source, heading, content)`. This means:
- Re-indexing unchanged documents reuses stable IDs.
- ChromaDB upserts by ID — no duplicate embeddings for unchanged content.
- However, since the current implementation does a full rebuild (delete + re-insert), the stability is not yet leveraged for incremental updates. **Future upgrade path: hash-based change detection to skip re-embedding unchanged documents.**

---

---

# RAG 说明文档 — AI-RAG-site-chat（中文翻译）

> **中文翻译** | **English original** above

---

## 目录

1. [概述](#1-概述)
2. [RAG 流水线架构](#2-rag-流水线架构)
3. [数据源](#3-数据源)
4. [文档加载与解析](#4-文档加载与解析)
5. [分块策略](#5-分块策略)
6. [嵌入生成](#6-嵌入生成)
7. [向量存储](#7-向量存储)
8. [混合检索](#8-混合检索)
9. [提示词构建与安全护栏](#9-提示词构建与安全护栏)
10. [配置参考](#10-配置参考)
11. [API 端点（RAG 相关）](#11-api-端点rag-相关)
12. [设计决策与理由](#12-设计决策与理由)

---

## 1. 概述

**AI-RAG-site-chat** 是一个轻量级、自包含的检索增强生成（RAG）聊天机器人，可嵌入任何网站。它仅从配置的知识库中回答用户问题——知识库是存储在本地或 GitHub 仓库中的一组文档（Markdown、HTML、JSON、纯文本）。

### 核心原则

| 原则 | 实现 |
|------|------|
| **来源接地** | 所有答案必须引用知识库内容；护栏提示词明确禁止编造 |
| **零本地模型下载** | 嵌入和 LLM 推理均通过 OpenRouter API 提供服务 |
| **混合检索** | 向量相似度 + BM25 关键词搜索，通过倒数排名融合（RRF）合并 |
| **单进程架构** | 无外部数据库、无消息队列、无微服务——一个 FastAPI 进程完成所有工作 |
| **可插拔人设** | AI 身份、语气和专业领域定义在可编辑的 `PERSONA.md` 文件中 |

### 技术栈速览

| 层级 | 技术 |
|------|------|
| 后端 | FastAPI + uvicorn（Python 3.11+） |
| 向量存储 | ChromaDB（持久化，HNSW 索引，余弦距离） |
| 关键词搜索 | rank-bm25（BM25Okapi） |
| 嵌入模型 | `openai/text-embedding-3-small`（1536 维），通过 OpenRouter |
| LLM | `deepseek/deepseek-v4-flash`（主）、`google/gemini-2.0-flash-001`（备），通过 OpenRouter |
| 前端 | React 18 + TypeScript + Tailwind CSS + framer-motion |
| 部署 | Docker + docker-compose，GitHub Actions CI/CD 推送至 ghcr.io |

---

## 2. RAG 流水线架构

流水线分为两个阶段：**索引构建**（离线/启动时）和**检索**（在线/每次查询）。

```
┌─────────────────────────────────────────────────────┐
│                    索引构建阶段                       │
│                                                     │
│  DATA_DIR ──► 加载器 ──► 文档 ──► 分块              │
│  （文件或     （md/html/  [{路径,   （标题感知        │
│   GitHub）    json/txt）  内容}]   递归拆分）         │
│                                      │               │
│              ┌──────────────────────┘               │
│              ▼                                      │
│        分块 [{id, 文本, 来源, 标题}]                 │
│              │                                      │
│     ┌────────┴────────┐                             │
│     ▼                 ▼                             │
│  嵌入 API          分词 + BM25                       │
│  （批量=50）       （构建语料索引）                   │
│     │                 │                             │
│     ▼                 ▼                             │
│  ChromaDB          内存                             │
│  （余弦 HNSW）      BM25Okapi 索引                   │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│                    检索阶段                           │
│                                                     │
│  用户查询 "什么是铜矿勘探？"                          │
│         │                                            │
│    ┌────┴────┐                                      │
│    ▼         ▼                                      │
│  嵌入查询   分词查询                                  │
│    │         │                                      │
│    ▼         ▼                                      │
│  ChromaDB  BM25                                     │
│  Top-50   Top-50                                    │
│  （余弦     （关键词                                  │
│   过滤      分数）                                    │
│   ≥0.5）                                            │
│    │         │                                      │
│    └────┬────┘                                      │
│         ▼                                           │
│    RRF 融合                                          │
│    分数 = Σ 1/(60+排名)                             │
│         │                                           │
│         ▼                                           │
│    Top-20 分块 ──► 系统提示词 ──► LLM ──► 答案      │
└─────────────────────────────────────────────────────┘
```

---

## 3. 数据源

三种互斥模式，按优先级解析：

| 优先级 | 来源 | 配置 | 机制 |
|--------|------|------|------|
| 1 | **本地目录** | `DATA_DIR=/path/to/docs` | 直接文件系统扫描，递归 |
| 2 | **GitHub 仓库** | `DATA_DIR=https://github.com/user/repo` | 稀疏克隆（depth-1，无 blob）→ 重建时 `git pull --ff-only` |
| 3 | **默认目录** | （未设置） | 回退到 `knowledge-base/` |

### GitHub 源行为

- **首次**：`git clone --depth 1 --filter=blob:none --sparse <url>` 到 `.github_cache/`
- **后续重建**：`git pull --ff-only` 增量更新
- **缓存目录**：`.github_cache/`（通过 Docker named volume `github_cache` 持久化）
- 稀疏检出后像本地目录一样通过相同的加载器流水线扫描。

---

## 4. 文档加载与解析

所有加载器位于 `backend/parsers/`。每个返回 `[{path: str, content: str}]`。

### 4.1 Markdown 加载器（`md_loader.py`）
- 原样读取 `.md` 文件，保留原始 Markdown 格式。
- 原始 Markdown 有意保留——LLM 原生理解 Markdown 语法。

### 4.2 HTML 加载器（`html_loader.py`）
- 使用 BeautifulSoup 提取语义内容。
- **优先级提取顺序**：
  1. `<article>`、`<section>`、`<main>`——保留标题层级（h1-h4）
  2. 回退到段落结构（`<p>`、`<li>`）
  3. 最终回退到 `.get_text()` 纯文本
- 提取前剥离 `<script>`、`<style>`、`<nav>`、`<footer>`。

### 4.3 JSON 加载器（`json_loader.py`）
- 将结构化 JSON 扁平化为叙述文本。
- **数组**：每个元素成为带索引标签的独立条目（"项目 1：……"）。
- **对象**：键值对渲染为命名段落。识别语义键：`title`、`content`、`summary`、`date`、`source`、`tags`。
- **嵌套结构**：递归扁平化。

### 4.4 文本加载器（`txt_loader.py`）
- 直接将 `.txt` 文件读取为 UTF-8 文本。

### 扫描规则
- 递归遍历所有子目录。
- **跳过**：隐藏目录/文件（以 `.` 开头的名称）、ChromaDB 内部文件。
- 无文件数量或大小限制——仅受可用内存限制。

---

## 5. 分块策略

在 `rag_engine.py` 中实现的**三阶段、标题感知的递归拆分**。

### 第一阶段：按 Markdown 标题拆分（`_split_by_headings`）
```
文档
  ├── # 标题 1  ──► 段落（标题="标题 1"）
  │     H1 下的内容……
  ├── ## 标题 2  ──► 段落（标题="标题 1 > 标题 2"）
  │     H2 下的内容……
  └── ### 标题 3 ──► 段落（标题="标题 1 > 标题 2 > 标题 3"）
        H3 下的内容……
```
- 每个标题级别创建独立段落。
- 标题面包屑作为元数据保留，用于来源引用。

### 第二阶段：按句子拆分长段落（`_split_long_section`）
- 如果段落的估算 token 数超过 `CHUNK_SIZE`（默认：500），按句子拆分。
- **句子分隔符**：`。！？.!?\n`
- 带重叠的滑动窗口（`CHUNK_OVERLAP`，默认：50 token）以保持跨块上下文。

### 第三阶段：Token 估算（`_estimate_tokens`）
```
估算 token 数 = 中文字符数 / 1.5 + 英文数字字符数 / 4
```
- 这是启发式近似，不是真正的分词器。
- **捷径说明：O(n) 扫描；中英混合文本最大误差约 30%。可升级为 tiktoken 以获得精确计数。**

### 分块 ID 生成（`_make_chunk_id`）
```
chunk_id = MD5(来源路径 | 标题路径 | 文本内容)[:16]
```
- **稳定**：相同内容在重建时产生相同 ID。
- **确定性**：无随机性，无时间戳依赖。
- 支持去重——如果文档未更改，其分块保留相同的 ID。

### 配置参数

| 参数 | 默认值 | 描述 |
|------|--------|------|
| `CHUNK_SIZE` | 500 | 每个分块的最大 token 数（估算） |
| `CHUNK_OVERLAP` | 50 | 相邻分块之间的 token 重叠量 |

---

## 6. 嵌入生成

### 模型
- **默认**：`openai/text-embedding-3-small`（1536 维向量）
- **备选**（可通过 `EMBEDDING_MODEL` 配置）：
  - `google/text-embedding-004`（768 维，$0.0025/1M tokens）
  - `cohere/embed-multilingual-v3.0`（1024 维，$0.10/1M tokens）

### API 调用
```
POST https://openrouter.ai/api/v1/embeddings
Headers:
  Authorization: Bearer <OPENROUTER_API_KEY>
Body:
  {
    "model": "openai/text-embedding-3-small",
    "input": ["文本块 1", "文本块 2", ……]
  }
```

### 批处理
- **索引**：分块以 50 个为一组批量嵌入（`_embed_in_batches()`）。
- **查询**：单个查询嵌入，无需批处理。
- 超时：每次 API 调用 120 秒。

### 维度说明
不同嵌入模型产生不同维度的向量。ChromaDB 在首次插入时自动检测维度。在初始索引后更改 `EMBEDDING_MODEL` 需要**完全重建**（`POST /api/rebuild-index`）。

---

## 7. 向量存储

### ChromaDB 配置
```python
chromadb.PersistentClient(path=".chroma_db/")
collection = get_or_create_collection(
    name="knowledge",
    metadata={"hnsw:space": "cosine"}
)
```

| 属性 | 值 |
|------|-----|
| **存储** | 持久化，本地文件系统（`.chroma_db/`） |
| **索引** | HNSW（分层导航小世界图） |
| **距离度量** | 余弦距离 |
| **集合** | 名为 `knowledge` 的单个集合 |
| **每个块的元数据** | `{source: 文件路径, heading: 标题路径}` |

### 持久化
- **本地**：项目根目录下的 `.chroma_db/` 目录。
- **Docker**：Docker named volume `chroma_data` 挂载在 `/app/.chroma_db`。
- 容器重启后仍然存在。不在实例间共享（单服务器设计）。

### 一致性保证
- BM25 索引和 ChromaDB 在启动时和手动重建时一起原子性地重建。
- 无增量更新——每次从头重建整个索引。
- **捷径说明：每次更改 O(N) 重建。对于约 10K 文档以下的知识库可接受。对于更大的知识库，考虑使用文档哈希跟踪的增量索引。**

---

## 8. 混合检索

这是核心检索策略。它结合**语义搜索**（向量）和**关键词搜索**（BM25），以最大化概念查询和精确术语匹配的召回率。

### 8.1 向量搜索（语义）

```
1. 嵌入用户查询 → 1536 维向量
2. ChromaDB.query(query_embeddings=[vector], n_results=CANDIDATE_K)
3. 过滤：仅保留余弦距离 > MIN_SIMILARITY（默认：0.5）的块
4. 结果：vector_ranked = [(chunk_id, distance), ……]
```

- `MIN_SIMILARITY` 作为相关性门控——低于阈值的分块被丢弃。
- 设置 `MIN_SIMILARITY=1.0` 可禁用过滤（接受所有候选项）。
- 较低的值（如 0.3）更宽松；较高的值（如 0.7）更严格。

### 8.2 BM25 关键词搜索（词汇）

```
1. 分词用户查询（中文：字符 unigram + bigram；英文：空白分词）
2. BM25Okapi.get_scores(tokenized_query)
3. 取前 CANDIDATE_K 个结果
4. 结果：bm25_ranked = [(chunk_id, score), ……]
```

#### 分词器设计（`_tokenize`）

专为**中英混合**文本设计，零外部 NLP 依赖：

| 语言 | 策略 | 示例 |
|------|------|------|
| 中文 | 字符 unigram + bigram | "铜矿" → `["铜", "铜矿", "矿"]` |
| 英文 | 空白分词，小写化，去标点 | "Copper Mining" → `["copper", "mining"]` |
| 数字 | 视为英文 token | "2024产量" → `["2024", "产", "产量", "量"]` |

**捷径说明：bigram 方法能处理大多数中文复合词，但会遗漏 3 字以上复合词如"锂电池"。升级路径：集成 jieba 并配置领域术语自定义词典。**

### 8.3 RRF 融合（倒数排名融合）

```
对于两个结果集中出现的每个唯一切块：
  rrf_score = Σ 1 / (60 + 在各列表中的排名)
```

- `k=60` 是原始论文推荐的标准 RRF 常数。
- 同时出现在两个结果集中的分块会得到加强（两个排名相加）。
- 最终输出：按 RRF 分数排序的前 `RETRIEVAL_K`（默认：20）个分块。

**为什么用 RRF 而不是 LLM 重排序？**
- RRF **零成本**（无需额外 API 调用）。
- RRF **确定性**（检索中无 LLM 随机性或幻觉风险）。
- 实践中，向量 + BM25 的组合已经提供足够的精度；LLM 重排序增加延迟和成本，收益有限。

### 8.4 配置参数

| 参数 | 默认值 | 描述 |
|------|--------|------|
| `RETRIEVAL_K` | 20 | 传递给 LLM 的最终分块数 |
| `RETRIEVAL_CANDIDATE_K` | 50 | 每种搜索方法的候选数 |
| `MIN_SIMILARITY` | 0.5 | 余弦距离阈值（越低越严格） |

---

## 9. 提示词构建与安全护栏

### 9.1 系统提示词结构

最终系统提示词是在 `persona.py` 中构建的**四层组装**：

```
┌──────────────────────────────────────┐
│ 第一层：人设（PERSONA）              │
│ PERSONA.md 的内容                    │
│ → AI 身份、语气、专业领域            │
├──────────────────────────────────────┤
│ 第二层：知识上下文（KNOWLEDGE CONTEXT）│
│ 格式化的检索分块：                    │
│                                      │
│ [来源: report.md] — 铜矿分析         │
│ 智利的铜矿勘探活动持续增长……          │
│ ---                                  │
│ [来源: data.json] — 黄金价格          │
│ 本周黄金价格波动……                   │
├──────────────────────────────────────┤
│ 第三层：引用规则（CITING）            │
│ "引用信息时始终注明源文件和标题。"     │
├──────────────────────────────────────┤
│ 第四层：安全护栏（GUARDRAILS）        │
│ 1. 来源接地                          │
│ 2. 保持角色                          │
│ 3. 范围边界                          │
│ 4. 回复格式                          │
│ 5. 回复长度                          │
└──────────────────────────────────────┘
```

### 9.2 护栏详情

| # | 规则 | 描述 |
|---|------|------|
| 1 | **来源接地** | 仅使用知识库中的信息。如果答案不在提供的上下文中，如实说明。绝不编造。 |
| 2 | **保持角色** | 保持 PERSONA.md 中定义的人设。不打破第四面墙或承认自己是 AI。 |
| 3 | **范围边界** | 礼貌拒绝超出人设领域的请求。重定向到定义的主题范围。 |
| 4 | **回复格式** | 仅纯文本。最终输出中不使用 HTML、不使用 Markdown 格式（知识上下文为 LLM 理解而格式化，非用户显示）。 |
| 5 | **回复长度** | 默认 2-4 句。简洁。仅在问题需要细节时扩展。 |

### 9.3 人设文件（`PERSONA.md`）

- 可编辑的 Markdown 文件，定义 AI 行为、专业知识和语气。
- **热重载**：编辑磁盘上的文件；更改在下一次请求时生效（无需重启）。
- Docker：以只读方式绑定挂载到 `/app/PERSONA.md`。

### 9.4 分块格式化（`_format_chunks`）

知识上下文中的每个分块格式化为：
```
[来源: relative/path/to/file.md] — 章节标题
分块文本内容……
---
```
- 来源路径相对于 `DATA_DIR` 根目录。
- 章节标题显示面包屑路径（如 "第 1 章 > 第 2 节"）。
- 分隔符 `---` 用于视觉清晰度。

---

## 10. 配置参考

所有参数从环境变量（`.env` 文件或 Docker 环境变量）读取。完整模板见 `.env.example`。

### 10.1 必需

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `OPENROUTER_API_KEY` | *（必需）* | 用于嵌入 + LLM 的 OpenRouter API 密钥 |

### 10.2 数据源

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `DATA_DIR` | *（空）* | 本地文档路径或 GitHub URL。回退到 `knowledge-base/` |
| `KNOWLEDGE_BASE_DIR` | `knowledge-base/` | 备选回退目录 |
| `PERSONA_FILE` | `PERSONA.md` | 人设定义文件路径 |
| `GITHUB_CACHE_DIR` | `.github_cache/` | GitHub 稀疏克隆缓存目录 |

### 10.3 RAG 参数

| 变量 | 默认值 | 范围 | 描述 |
|------|--------|------|------|
| `EMBEDDING_MODEL` | `openai/text-embedding-3-small` | 任何 OpenRouter 嵌入模型 | 嵌入模型 ID |
| `CHUNK_SIZE` | `500` | 100-2000 | 每个分块的最大估算 token 数 |
| `CHUNK_OVERLAP` | `50` | 0-500 | 分块之间的 token 重叠量 |
| `RETRIEVAL_K` | `20` | 1-100 | 传递给 LLM 的分块数 |
| `RETRIEVAL_CANDIDATE_K` | `50` | 10-500 | 每种搜索方法的候选数 |
| `MIN_SIMILARITY` | `0.5` | 0.0-2.0 | 向量搜索的余弦距离阈值 |

### 10.4 LLM 参数

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `OPENROUTER_MODEL` | `deepseek/deepseek-v4-flash,google/gemini-2.0-flash-001` | 逗号分隔的模型列表（故障转移链） |
| `MAX_TOKENS` | `1024` | 每次聊天回复的最大输出 token |
| `TEMPERATURE` | `0.6` | 聊天的 LLM 温度 |
| `SUGGEST_MAX_TOKENS` | `200` | 追问建议的最大 token |
| `SUGGEST_TEMPERATURE` | `0.7` | 建议的 LLM 温度 |
| `MAX_HISTORY` | `20` | 保留在上下文中的最大对话轮次 |
| `MAX_CHARS` | `4000` | 单条消息的最大字符数 |
| `MAX_CONCURRENT_LLM` | `5` | 最大并发 LLM API 调用数 |

### 10.5 安全与服务

| 变量 | 默认值 | 描述 |
|------|--------|------|
| `CORS_ORIGIN` | `*` | 逗号分隔的允许来源 |
| `RATE_LIMIT_CHAT_MAX` | `20` | 每个窗口的聊天请求数 |
| `RATE_LIMIT_CHAT_WINDOW` | `60` | 聊天速率限制窗口（秒） |
| `RATE_LIMIT_SUGGEST_MAX` | `30` | 每个窗口的建议请求数 |
| `RATE_LIMIT_SUGGEST_WINDOW` | `60` | 建议速率限制窗口（秒） |
| `RATE_LIMIT_REBUILD_MAX` | `3` | 每个窗口的重建请求数 |
| `RATE_LIMIT_REBUILD_WINDOW` | `300` | 重建速率限制窗口（秒） |
| `REBUILD_SECRET` | *（空 = 禁用）* | `/api/rebuild-index` 保护的密钥 |
| `PORT` | `8000` | HTTP 服务器端口 |

---

## 11. API 端点（RAG 相关）

### 11.1 GET `/api/health`

返回索引状态。无需认证。

**响应：**
```json
{
  "status": "ok",
  "has_index": true,
  "chunk_count": 42,
  "has_bm25": true,
  "retrieval_k": 20,
  "candidate_k": 50,
  "min_similarity": 0.5
}
```

### 11.2 POST `/api/chat`

带 RAG 检索的主聊天端点。

**请求：**
```json
{
  "messages": [
    {"role": "user", "content": "铜矿勘探的现状如何？"}
  ],
  "sessionId": "可选会话 ID"
}
```

**响应：** `text/plain` 流式——每个块是 LLM 的原始文本 token。

**处理流程：**
1. 来源验证（CORS）
2. 速率限制检查（滑动窗口，按 IP，默认 20 次/分钟）
3. 消息清洗（角色过滤、长度截断、历史限制）
4. RAG 检索（混合搜索 → RRF 融合 → Top-K 分块）
5. 系统提示词组装（人设 + 分块 + 护栏）
6. 带自动模型故障转移的流式 LLM 调用
7. 输出清洗（去除 HTML 标签/URL）

### 11.3 POST `/api/suggest`

生成 3 个上下文追问问题。不执行 RAG 检索——纯基于对话上下文。

### 11.4 POST `/api/rebuild-index`

强制重建整个知识库索引。可选通过 `x-rebuild-secret` 头使用 `REBUILD_SECRET` 保护。

**处理：**
1. 重新扫描数据源（本地文件或 `git pull` 用于 GitHub）
2. 重新解析所有文档
3. 使用当前 `CHUNK_SIZE`/`CHUNK_OVERLAP` 设置重新分块
4. 重新嵌入所有分块并重建 ChromaDB 集合
5. 重建 BM25 索引

### 速率限制

| 端点 | 默认限制 |
|------|----------|
| `/api/chat` | 20 次请求 / 60 秒 |
| `/api/suggest` | 30 次请求 / 60 秒 |
| `/api/rebuild-index` | 3 次请求 / 300 秒 |

速率限制使用按客户端 IP 键控的**滑动窗口**算法。所有限制可通过环境变量配置。

---

## 12. 设计决策与理由

### 12.1 为什么使用混合检索（而非纯向量搜索）？

向量搜索擅长语义相似度，但在以下方面存在困难：
- **精确术语**（如 "ROE 15.3%"、产品代码、法律条款编号）
- **罕见领域术语**，可能在嵌入训练数据中表示不佳
- **否定和精确条件**（"不包括铜"、"2023 年之前"）

BM25 通过匹配字面 token 填补这些空白。RRF 融合将两者结合，无需 LLM 重排序的延迟和成本。

### 12.2 为什么不使用 LLM 重排序？

- **延迟**：每次额外的 LLM 调用增加 500ms-2s。
- **成本**：对 N 个候选项重排序的成本约为 (N × 平均块 token 数) 输入 token。
- **边际效益递减**：测试中，LLM 重排序相对 RRF 的精度提升有限（<5%）。
- **确定性**：RRF 可复现；LLM 重排序是随机的。

### 12.3 为什么使用单进程架构？

- **简洁**：无需 Redis、PostgreSQL、消息队列。一个 `docker-compose up` 部署所有内容。
- **充分性**：对于约 10K 文档以下的知识库和中等流量，带有内存 BM25 和本地 ChromaDB 的单进程绰绰有余。
- **权衡**：不可水平扩展。对于多实例部署，ChromaDB 和 BM25 需要外部化。

### 12.4 为什么没有外部 NLP 依赖？

分词器对中文使用字符级 unigram+bigram，对英文使用空白分词——无 jieba、无 spaCy、无 NLTK。这使得 Docker 镜像较小（约 200MB），避免版本冲突。

**已知限制**：3 字以上中文复合词（"锂电池"、"人工智能"）可能无法作为单个 token 匹配。对于领域特定知识库，考虑添加自定义词典或集成 jieba。

### 12.5 为什么余弦距离 ≥ 0.5？

经过实证测试，余弦距离低于 0.5 的分块与查询向量的相关性始终不足。此阈值作为**质量门控**——防止 LLM 接收可能触发幻觉的噪声。可按领域调整：事实/技术内容更严格（0.3-0.4），创意/开放式内容更宽松（0.6-0.7）。

### 12.6 为什么使用稳定的分块 ID？

分块 ID 是 `(来源, 标题, 内容)` 的 MD5 哈希。这意味着：
- 重新索引未更改的文档会重用稳定 ID。
- ChromaDB 按 ID upsert——未更改内容不会产生重复嵌入。
- 然而，由于当前实现进行完全重建（删除 + 重新插入），稳定性尚未用于增量更新。**未来升级路径：基于哈希的变更检测以跳过未更改文档的重新嵌入。**

---

> **Document version**: 1.0 | **Last updated**: 2025-07-09 | **Project**: AI-RAG-site-chat
