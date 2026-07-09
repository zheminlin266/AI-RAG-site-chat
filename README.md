# RAG Site Chat

[中文版](./README.zh-CN.md)

**RAG-powered AI chat widget for any static website.** Drop in your documents, write a persona, add your API key — your site visitors can chat with your content in under 5 minutes.

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/vector_db-ChromaDB-FF6F00" alt="ChromaDB">
  <img src="https://img.shields.io/badge/llm-OpenRouter-6366f1" alt="OpenRouter">
  <img src="https://img.shields.io/badge/frontend-React_18-61DAFB?logo=react" alt="React">
</p>

---

## What it does

A floating chat button appears on your website. Visitors click it, ask questions, and get answers grounded in **your** content — your blog posts, your docs, your data. The AI only knows what you give it.

- RAG (Retrieval-Augmented Generation): answers are grounded in your documents, not hallucinated
- Multi-format: Markdown, HTML, JSON, plain text — drop anything in
- API-based embeddings: no local model download — everything goes through OpenRouter
- Streaming responses: words appear as they're generated
- Model fallback: if one LLM fails, it tries the next automatically
- Follow-up suggestions: keeps the conversation going
- Same-origin protection: only your site can call the API
- GitHub data sources: point to any public repo folder — auto clone & sync

---

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/your-org/AI-RAG-site-chat.git
cd AI-RAG-site-chat
pip install -r requirements.txt
```

### 2. Add your content — pick one of three ways

**Option A: Local folder** (recommended for most users)

```bash
# .env
DATA_DIR=D:\Projects\my-site\docs
```

**Option B: GitHub repo folder** (live sync from any public repo)

```bash
# .env
DATA_DIR=https://github.com/user/repo/tree/main/docs
```

The server auto-clones the repo using sparse checkout (depth-1, blobless — fast even for large repos).
On rebuild, it runs `git pull` to fetch latest changes.

**Option C: Default `knowledge-base/` folder** (no `.env` change needed)

```
knowledge-base/
├── about-me.md           # Markdown (auto-detected)
├── blog-posts/           # Subdirectories work
│   ├── post-1.html
│   └── post-2.html
├── data.json             # Structured JSON
└── notes.txt             # Plain text
```

Supported formats: `.md` `.html` `.htm` `.json` `.txt`

### 3. Write your persona

Edit `PERSONA.md` — this is the AI's voice, identity, and behavior:

```markdown
You are the site owner, answering questions in first person.
You're a geologist specializing in copper exploration...
```

See [PERSONA.md](./PERSONA.md) for the full template.

### 4. Add your API key

```bash
cp .env.example .env
# Edit .env → paste your OpenRouter API key
```

Get a key at [openrouter.ai](https://openrouter.ai/) (free credits on signup).

### 5. Start the server

```bash
python -m backend.server
# → http://localhost:8000
# Index built automatically on first start
```

### 6. Add the widget to your site

Drop `<AiChat />` into your React/Next.js app:

```tsx
import { AiChat } from "./components/ai-chat";

// In your layout or page:
<AiChat
  apiBase="http://localhost:8000"   // or "/api" behind nginx
  label="Ask me anything"
  suggestions={["What's your background?", "Tell me about your work"]}
  emptyMessage="Ask me about the content on this site."
/>
```

Or embed as a vanilla script (see [frontend/README.md](./frontend/README.md) for details).

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Your Website                           │
│  ┌──────────────────────────────────────────────────┐   │
│  │            ai-chat.tsx (Chat Widget)               │   │
│  │  · Floating button → chat panel                   │   │
│  │  · Streaming token rendering                      │   │
│  │  · Session management                             │   │
│  │  · Follow-up suggestions                          │   │
│  └─────────────┬────────────────────────────────────┘   │
│                │ POST /api/chat                          │
└────────────────┼────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│             server.py (FastAPI)                           │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │ Origin   │  │ Sanitize │  │ Stream Response (SSE) │   │
│  │ Check    │  │ Messages │  │                       │   │
│  └──────────┘  └──────────┘  └──────────────────────┘   │
│        │              │               │                   │
│  ┌─────▼──────────────▼───────────────▼──────────────┐   │
│  │              Processing Pipeline                    │   │
│  │  Persona (PERSONA.md) + RAG Context + Guardrails   │   │
│  └──────────────────────┬────────────────────────────┘   │
│                         │                                 │
│  ┌──────────────────────▼────────────────────────────┐   │
│  │            OpenRouter API Call                      │   │
│  │  Model 1 → fail? → Model 2 → fail? → error        │   │
│  └───────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│              rag_engine.py (RAG Engine)                    │
│                                                           │
│  Data sources: Local folder │ GitHub repo │ knowledge-base/ │
│  ┌─────────────┐   ┌─────────────┐   ┌───────────────┐  │
│  │ Doc Loader  │──▶│ Chunk       │──▶│ OpenRouter    │  │
│  │ .md .html   │   │ Splitter    │   │ Embed API     │  │
│  │ .json .txt  │   │ by headings │   │ → ChromaDB    │  │
│  └─────────────┘   └─────────────┘   └───────┬───────┘  │
│                                              │           │
│                          Query → embed API → search Top-K │
└──────────────────────────────────────────────────────────┘
```

### Data flow (per request)

1. User types a question → `POST /api/chat`
2. **Origin check** — only same-origin requests allowed
3. **Message sanitization** — max 4000 chars, max 20 history rounds
4. **RAG retrieval** — query embedded, Top-5 chunks from ChromaDB
5. **Prompt assembly** — Persona + retrieved context + citing rules + guardrails
6. **LLM call** — streaming via OpenRouter, automatic model fallback
7. **Streaming response** — tokens flow to frontend as they're generated
8. **Follow-up suggestions** — 3 relevant questions generated after reply

---

## Security

| Layer | Measure |
|-------|---------|
| **Transport** | Origin header validation — only your domain can call the API |
| **Input** | Message type validation, 4000-char cap, 20-round history limit |
| **Model** | Guardrails prompt prevents jailbreaking, hallucination, out-of-scope answers |
| **Deployment** | API key stored server-side only (`OPENROUTER_API_KEY` in `.env`), never exposed to frontend |
| **CORS** | Configurable `CORS_ORIGIN` — restrict to your domain in production |

The AI **cannot** access the internet, training data, or anything outside your knowledge base. It only knows what you give it.

---

## Customization

### Change the AI model

```bash
# .env
OPENROUTER_MODEL=deepseek/deepseek-v4-flash,google/gemini-2.0-flash-001
```

Default: DeepSeek V4 Flash → Gemini Flash fallback. Any [OpenRouter model](https://openrouter.ai/models) works.

### Change the embedding model

Embeddings go through OpenRouter API — no local model download needed. Default is `openai/text-embedding-3-small` (1536-dim, $0.02/1M tokens).

To switch, set in `.env`:

```bash
EMBEDDING_MODEL=openai/text-embedding-3-small
```

| Model | Dimensions | Cost/1M tokens | Best for |
|-------|-----------|----------------|----------|
| `openai/text-embedding-3-small` | 1536 | $0.02 | General (default) |
| `google/text-embedding-004` | 768 | $0.0025 | Budget |
| `cohere/embed-multilingual-v3.0` | 1024 | $0.10 | Multilingual |

### Customize guardrails

Edit `backend/persona.py` → `GUARDRAILS` section to adjust:
- Source grounding strictness
- Scope boundaries (what the AI can/can't answer)
- Response length defaults
- Language behavior

### Update knowledge live

```bash
# After adding/modifying files, rebuild the index:
curl -X POST http://localhost:8000/api/rebuild-index
```

No restart needed. With GitHub sources, rebuild also runs `git pull` to fetch the latest content.

### GitHub source internals

When `DATA_DIR` points to a GitHub URL like `https://github.com/user/repo/tree/main/docs`:

1. **Sparse clone**: `git clone --depth 1 --filter=blob:none --sparse` — fetches only metadata and the target folder, not the entire repo history
2. **Local cache**: stored in `.github_cache/{owner}_{repo}/`, reused across restarts
3. **Auto-pull**: on rebuild, runs `git pull --ff-only` to get latest changes
4. **Requires**: `git` installed on the server (standard on most systems)

---

## API Reference

### `GET /api/health`

```json
{
  "status": "ok",
  "has_index": true,
  "chunk_count": 42,
  "models": ["deepseek/deepseek-v4-flash", "google/gemini-2.0-flash-001"]
}
```

### `POST /api/chat`

Request:
```json
{
  "messages": [
    { "role": "user", "content": "What do you work on?" }
  ],
  "sessionId": "abc123"
}
```

Response: `text/plain` streaming, one token per chunk.

### `POST /api/suggest`

Request: same shape as chat.

Response:
```json
{
  "suggestions": [
    "What tools do you use?",
    "How did you get started?",
    "What's your favorite project?"
  ]
}
```

### `POST /api/rebuild-index`

Rebuilds the knowledge base index. Returns: `{ "status": "ok", "chunk_count": 42 }`

---

## Deployment

### Option A: Behind nginx (recommended)

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

Then point `apiBase="/api"` in the frontend — no CORS issues, same origin.

### Option B: Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "-m", "backend.server"]
```

### Option C: GitHub Pages + separate backend

Host your static site on GitHub Pages, run the backend on a $5 VPS or [Fly.io](https://fly.io) / [Railway](https://railway.app). Set `CORS_ORIGIN=https://your-site.github.io` in `.env`.

---

## Project structure

```
AI-RAG-site-chat/
├── README.md
├── PERSONA.md              # Your AI persona (edit this)
├── .env.example            # Config template
├── requirements.txt
├── package.json
│
├── backend/
│   ├── server.py           # FastAPI server (4 endpoints)
│   ├── rag_engine.py       # RAG pipeline (load → chunk → embed → search)
│   ├── persona.py          # Loads PERSONA.md + builds system prompt
│   ├── chat_util.py        # Origin check, sanitize, HTTP client, rate limiter
│   ├── config.py           # All config via env vars
│   ├── github_source.py    # GitHub repo folder clone & cache
│   └── parsers/
│       ├── md_loader.py    # Markdown parser
│       ├── html_loader.py  # HTML parser (BeautifulSoup)
│       ├── json_loader.py  # JSON structured data parser
│       └── txt_loader.py   # Plain text parser
│
├── frontend/
│   └── ai-chat.tsx         # React chat widget (887 lines)
│
└── knowledge-base/         # Your documents go here
    └── .gitkeep
```

---

## Acknowledgments

Inspired by [pedromello.cc](https://pedromello.cc)'s "Ask me anything" module. Built with [FastAPI](https://fastapi.tiangolo.com/), [ChromaDB](https://www.trychroma.com/), and [OpenRouter](https://openrouter.ai/) (LLM + embeddings).

---

## License

MIT — use it, fork it, ship it.
