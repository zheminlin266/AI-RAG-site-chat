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

![UI Wireframe](ui-wireframe.png)

- RAG (Retrieval-Augmented Generation): answers are grounded in your documents, not hallucinated
- Hybrid search: semantic (vector) + keyword (BM25) → RRF fusion — scales to large knowledge bases
- Smart filtering: cosine distance threshold drops irrelevant chunks — honest "I don't know" over forced answers
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
┌───────────────────────────────────────────────────────────┐
│                    Your Website                           │
│  ┌──────────────────────────────────────────────────┐     │
│  │            ai-chat.tsx (Chat Widget)               │   │
│  │  · Floating button → chat panel                   │   │
│  │  · Streaming token rendering                      │   │
│  │  · Session management                             │   │
│  │  · Follow-up suggestions                          │   │
│  └─────────────┬────────────────────────────────────┘     │
│                │ POST /api/chat                          │
└────────────────┼──────────────────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────────────────┐
│             server.py (FastAPI)                           │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐     │
│  │ Origin   │  │ Sanitize │  │ Stream Response (SSE) │   │
│  │ Check    │  │ Messages │  │                       │   │
│  └──────────┘  └──────────┘  └──────────────────────┘     │
│        │              │               │                   │
│  ┌─────▼──────────────▼───────────────▼──────────────┐    │
│  │              Processing Pipeline                    │   │
│  │  Persona (PERSONA.md) + RAG Context + Guardrails   │   │
│  └──────────────────────┬────────────────────────────┘    │
│                         │                                 │
│  ┌──────────────────────▼────────────────────────────┐    │
│  │            OpenRouter API Call                      │   │
│  │  Model 1 → fail? → Model 2 → fail? → error        │   │
│  └───────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────────────────┐
│              rag_engine.py (RAG Engine)                    │
│                                                           │
│  Data sources: Local folder │ GitHub repo │ knowledge-base/ │
│  ┌─────────────┐   ┌─────────────┐   ┌───────────────┐    │
│  │ Doc Loader  │──▶│ Chunk       │──▶│ OpenRouter    │  │
│  │ .md .html   │   │ Splitter    │   │ Embed API     │  │
│  │ .json .txt  │   │ by headings │   │ → ChromaDB    │  │
│  └─────────────┘   └─────────────┘   └───────┬───────┘    │
│                                              │           │
│           ┌──────────────────────────────────┘            │
│           │                                              │
│           ▼                                              │
│    ┌──────────────┐     ┌──────────────┐                  │
│    │ Vector search│     │ BM25 keyword │                 │
│    │ (semantic)   │     │ (exact match)│                 │
│    └──────┬───────┘     └──────┬───────┘                  │
│           │                    │                          │
│           └────────┬───────────┘                          │
│                    ▼                                      │
│            ┌──────────────┐                               │
│            │ RRF fusion   │                               │
│            │ → distance   │                               │
│            │   threshold  │                               │
│            │ → Top-20     │                               │
│            └──────────────┘                               │
└───────────────────────────────────────────────────────────┘
```

### Data flow (per request)

1. User types a question → `POST /api/chat`
2. **Origin check** — only same-origin requests allowed
3. **Message sanitization** — max 4000 chars, max 20 history rounds
4. **Hybrid retrieval** — vector (semantic) + BM25 (keyword) → RRF fusion → distance threshold → Top-20
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

### Tune retrieval

```bash
# .env
# Final chunk count sent to LLM (default 20)
RETRIEVAL_K=20

# Candidate pool size for vector and BM25 searches (default 50)
RETRIEVAL_CANDIDATE_K=50

# Cosine distance threshold — chunks above this are dropped as irrelevant (default 0.5)
# Lower = stricter filter. Set to 1.0 to disable filtering.
MIN_SIMILARITY=0.5
```

**Retrieval pipeline**:
1. Vector search (semantic) → CANDIDATE_K candidates → distance threshold filter
2. BM25 keyword search → CANDIDATE_K candidates
3. Reciprocal Rank Fusion merges both rankings → Top-RETRIEVAL_K

For small knowledge bases (<100 chunks), set `MIN_SIMILARITY=1.0` to disable filtering. Larger collections benefit from a tighter threshold.

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
  "has_bm25": true,
  "retrieval_k": 20,
  "candidate_k": 50,
  "min_similarity": 0.5,
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

## VPS Deployment

The architecture is simple: one Docker container running FastAPI, with a reverse proxy in front for HTTPS. No external database dependencies — ChromaDB persists to a Docker volume, and both the index and cache live on local disk.

```
Internet ──▶ Nginx/Caddy (HTTPS) ──▶ Docker container (FastAPI:8000)
```

### Prerequisites

- **VPS**: Ubuntu 22.04+ / Debian 12+, 1 vCPU 1 GB RAM minimum (2 GB recommended — the initial index build makes many embedding API calls)
- **Docker + Docker Compose**: [official install guide](https://docs.docker.com/engine/install/)
- **Domain name** (recommended): for HTTPS certificates
- **OpenRouter API Key**: sign up at [openrouter.ai](https://openrouter.ai/) for free credits

### Step 1: Get the project

```bash
git clone https://github.com/your-org/AI-RAG-site-chat.git
cd AI-RAG-site-chat

# Configure environment
cp .env.example .env
# Edit .env — paste your OPENROUTER_API_KEY
```

### Step 2: Add your knowledge base

```bash
# Drop your documents into knowledge-base/
cp /path/to/your/docs/*.md knowledge-base/
```

Or set `DATA_DIR` in `.env` to point to a local folder or GitHub repo.

### Step 3: Pick a deployment option

| Option | HTTPS | Best for |
|--------|-------|----------|
| [A. Plain Docker Compose](#option-a-plain-docker-compose) | Extra setup needed | Already have a reverse proxy / testing |
| [B. Docker + Caddy](#option-b-docker--caddy-recommended-simplest-https) | Automatic | **Recommended**: personal VPS, dead simple |
| [C. Docker + Nginx + Let's Encrypt](#option-c-docker--nginx--lets-encrypt) | Manual setup | Already running Nginx or need fine-grained control |

---

### Option A: Plain Docker Compose

Just the app container on port 8000. Good if you already have a reverse proxy or just want to test.

```bash
# Start
docker compose up -d

# Verify
curl http://localhost:8000/api/health
# → {"status":"ok","has_index":true,"chunk_count":42,"has_bm25":true,"retrieval_k":20}

# Logs
docker compose logs -f
```

Point your frontend at `apiBase="http://your-server-ip:8000"`. For HTTPS, keep reading.

---

### Option B: Docker + Caddy (Recommended, simplest HTTPS)

[Caddy](https://caddyserver.com/) auto-provisions and renews Let's Encrypt certificates — zero config HTTPS.

**1. Install Caddy**

```bash
# Ubuntu/Debian
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

**2. Start the app**

```bash
docker compose up -d
# App bound to 127.0.0.1:8000 — not reachable externally
```

**3. Configure Caddy**

Edit `/etc/caddy/Caddyfile`:

```caddy
chat.your-domain.com {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
# Certificate auto-provisioned — visit https://chat.your-domain.com
```

Point your frontend at `apiBase="https://chat.your-domain.com"`. Caddy handles TLS, HTTP→HTTPS redirect, and SSE/streaming out of the box.

---

### Option C: Docker + Nginx + Let's Encrypt

For existing Nginx setups or when you need fine-grained control.

**1. Start the app**

```bash
docker compose up -d
```

**2. Install Nginx + Certbot**

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

**3. Configure Nginx**

Create `/etc/nginx/sites-available/rag-chat`:

```nginx
server {
    listen 80;
    server_name chat.your-domain.com;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        # Required for SSE streaming
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Protect the rebuild-index endpoint
    location /api/rebuild-index {
        proxy_pass http://127.0.0.1:8000;
        # Optional: IP whitelist or basic auth
        # allow your-office-ip;
        # deny all;
    }
}
```

Key settings:
- `proxy_buffering off` + `proxy_cache off` — essential for SSE streaming
- `proxy_http_version 1.1` — enables keep-alive and chunked transfer

**4. Enable site + HTTPS**

```bash
sudo ln -s /etc/nginx/sites-available/rag-chat /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# Get a certificate
sudo certbot --nginx -d chat.your-domain.com

# Auto-renews every 90 days
```

---

### Data persistence

`docker-compose.yml` defines two named volumes — data survives container restarts and rebuilds:

| Volume | Mount path | What it stores |
|--------|-----------|----------------|
| `chroma_data` | `/app/.chroma_db` | Vector index (built on first start) |
| `github_cache` | `/app/.github_cache` | GitHub data source cache |

Knowledge base files are bind-mounted (`./knowledge-base:/app/knowledge-base:ro`) — edit them directly on the host.

### Updating

```bash
# Pull latest code
git pull

# Rebuild and restart
docker compose up -d --build

# If knowledge base has changed, rebuild index
curl -X POST http://localhost:8000/api/rebuild-index
```

### Logs & monitoring

```bash
# Live logs
docker compose logs -f

# Health check
curl https://chat.your-domain.com/api/health

# Resource usage
docker stats rag-chat
```

Pair with [Uptime Kuma](https://github.com/louislam/uptime-kuma) to monitor the `/api/health` endpoint, or add a simple cron:

```bash
# crontab -e
*/5 * * * * curl -fSs https://chat.your-domain.com/api/health || echo "RAG Chat down" | mail -s "Alert" you@example.com
```

### Security checklist

- Firewall: only open ports 80/443, **never** expose 8000
- Set `CORS_ORIGIN=https://your-domain.com` in `.env`
- Protect `/api/rebuild-index` with `REBUILD_SECRET` or nginx IP whitelist
- `docker compose pull` periodically to update base images (security patches)

---

## Project structure

```
AI-RAG-site-chat/
├── README.md
├── README.zh-CN.md
├── PERSONA.md              # Your AI persona (edit this)
├── .env.example            # Config template
├── requirements.txt        # Python deps (FastAPI, ChromaDB, rank-bm25...)
├── package.json
├── Dockerfile              # Container image
├── docker-compose.yml      # VPS one-command deploy
├── .dockerignore
│
├── backend/
│   ├── server.py           # FastAPI server (4 endpoints)
│   ├── rag_engine.py       # RAG pipeline (load → chunk → embed → hybrid search)
│   ├── persona.py          # Loads PERSONA.md + builds system prompt
│   ├── chat_util.py        # Origin check, sanitize, HTTP client, rate limiter
│   ├── config.py           # All config via env vars (incl. retrieval params)
│   ├── github_source.py    # GitHub repo folder clone & cache
│   └── parsers/
│       ├── md_loader.py    # Markdown parser
│       ├── html_loader.py  # HTML parser (BeautifulSoup)
│       ├── json_loader.py  # JSON structured data parser
│       └── txt_loader.py   # Plain text parser
│
├── frontend/
│   └── ai-chat.tsx         # React chat widget
│
└── knowledge-base/         # Your documents go here
    └── .gitkeep
```

---

## Acknowledgments

Inspired by [pedromello.cc](https://pedromello.cc)'s "Ask me anything" module. Built with [FastAPI](https://fastapi.tiangolo.com/), [ChromaDB](https://www.trychroma.com/), [rank-bm25](https://github.com/dorianbrown/rank_bm25), and [OpenRouter](https://openrouter.ai/) (LLM + embeddings).

---

## License

MIT — use it, fork it, ship it.
