# RAG Site Chat

**面向网站的 RAG AI 聊天组件。** React 项目可直接使用 React 组件；任意静态网站可复制零依赖的 `<ai-rag-chat>` Web Component。

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/vector_db-ChromaDB-FF6F00" alt="ChromaDB">
  <img src="https://img.shields.io/badge/llm-OpenRouter-6366f1" alt="OpenRouter">
  <img src="https://img.shields.io/badge/frontend-React_%2B_Web_Component-61DAFB" alt="React and Web Component">
</p>

> English Version: [README.md](./README.md)

---

## 它能做什么

网站右下角出现一个浮动聊天按钮。访客点击后提问，得到的回答基于**你的**内容——你的博客、文档、数据。检索与护栏会将这些内容作为回答事实的预期来源。

![UI Wireframe](ui-wireframe.png)

- **RAG（检索增强生成）**：回答扎根于你的文档，拒绝幻觉
- **混合检索**：语义搜索（向量）+ 关键词匹配（BM25）+ RRF 融合
- **智能过滤**：向量距离和正分 BM25 候选共同排除不相关内容
- **多格式支持**：Markdown、HTML、JSON、纯文本——直接丢进去
- **API 嵌入**：无需本地下载模型，全部通过 OpenRouter 接口
- **流式响应**：文字逐字生成，所见即所得
- **默认模型**：DeepSeek V4 Flash；如需回退模型，显式配置后才会启用
- **追问建议**：让对话持续下去
- **安全边界**：精确 Origin 白名单、请求体上限、限流、默认不暴露重建接口
- **GitHub 数据源**：指向公开仓库文件夹——稀疏克隆，并在重建时显式同步

---

## 快速开始

### 1. 克隆并安装

```bash
git clone https://github.com/zheminlin266/AI-RAG-site-chat.git
cd AI-RAG-site-chat
pip install -r requirements.txt
```

### 2. 添加你的内容——三选一

**方式 A：本地文件夹**（推荐）

```bash
# .env
DATA_DIR=D:\Projects\my-site\docs
```

**方式 B：GitHub 仓库文件夹**（自动同步公开仓库的最新内容）

```bash
# .env
DATA_DIR=https://github.com/user/repo/tree/main/docs
```

服务端自动使用稀疏检出（sparse checkout）克隆——仅拉取目标文件夹，速度快，即使是大型仓库也不影响。

**方式 C：默认 `knowledge-base/` 文件夹**（无需改动 `.env`）

```
knowledge-base/
├── about-me.md           # Markdown（自动识别）
├── blog-posts/           # 子目录也支持
│   ├── post-1.html
│   └── post-2.html
├── data.json             # 结构化 JSON
└── notes.txt             # 纯文本
```

支持格式：`.md` `.html` `.htm` `.json` `.txt`

### 3. 编写人格设定

编辑 `PERSONA.md`——这里定义 AI 的语气、身份和行为：

```markdown
你是这个网站的博主，以第一人称回答问题。
你是一位专注于铜矿勘探的地质学家……
```

完整模板参见 [PERSONA.md](./PERSONA.md)。

### 4. 填入 API Key

```bash
cp .env.example .env
# 编辑 .env → 粘贴你的 OpenRouter API Key
```

在 [openrouter.ai](https://openrouter.ai/) 注册即可获取 Key（注册即送免费额度）。

### 5. 启动服务

```bash
python -m backend.server
# → http://localhost:8000
# 首次启动自动构建索引
```

### 6a. 在 React 项目中添加组件

将 [frontend/ai-chat.tsx](./frontend/ai-chat.tsx) 复制到已使用 React 18+、Tailwind CSS 和 Framer Motion 的项目中，再渲染 `<AiChat />`：

```tsx
import { AiChat } from "./components/ai-chat";

// 放在布局或页面中：
<AiChat
  apiBase="http://localhost:8000"   // 或通过 nginx 代理后的 "/api"
  label="随便问我"
  suggestions={["你的背景是什么？", "聊聊你的工作内容"]}
  emptyMessage="向我询问这个网站上的内容吧。"
/>
```

### 6b. 在任意静态网站中添加 standalone Web Component

将 `frontend/standalone/ai-rag-chat.js` 复制到网站静态资源目录，再添加：

```html
<script src="/assets/ai-rag-chat.js" defer></script>
<ai-rag-chat
  api-base="https://chat.example.com"
  label="随便问我"
  language="zh-CN"
  storage="local"
></ai-rag-chat>
```

该 bundle 不依赖 React、Tailwind 或任何运行时库。如果后端与承载组件的网站跨域，请在后端设置 `CORS_ORIGIN=https://your-site.example`，其值必须与网站 Origin 完全一致。

---

## 架构

```
┌───────────────────────────────────────────────────────────┐
│                    你的网站                               │
│  ┌──────────────────────────────────────────────────┐     │
│  │            ai-chat.tsx（聊天组件）                 │   │
│  │  · 浮动按钮 → 聊天面板                            │   │
│  │  · 流式逐字渲染                                    │   │
│  │  · 会话管理                                       │   │
│  │  · 追问建议                                       │   │
│  └─────────────┬────────────────────────────────────┘     │
│                │ POST /api/chat                          │
└────────────────┼──────────────────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────────────────┐
│             server.py (FastAPI)                           │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐     │
│  │ 来源校验 │  │ 请求校验 │  │ 流式响应              │   │
│  └──────────┘  └──────────┘  └──────────────────────┘     │
│        │              │               │                   │
│  ┌─────▼──────────────▼───────────────▼──────────────┐    │
│  │              处理管线                              │   │
│  │  人格 (PERSONA.md) + RAG 上下文 + 安全护栏        │   │
│  └──────────────────────┬────────────────────────────┘    │
│                         │                                 │
│  ┌──────────────────────▼────────────────────────────┐    │
│  │            OpenRouter API 调用                     │   │
│  │  模型1 → 失败？→ 模型2 → 失败？→ 报错            │   │
│  └───────────────────────────────────────────────────┘    │
└───────────────────────────────────────────────────────────┘
                 │
┌────────────────▼──────────────────────────────────────────┐
│              rag_engine.py (RAG 引擎)                     │
│                                                           │
│  数据来源: 本地文件夹 │ GitHub 仓库 │ knowledge-base/     │
│  ┌─────────────┐   ┌─────────────┐   ┌───────────────┐    │
│  │ 文档加载器  │──▶│ 切片器      │──▶│ OpenRouter    │  │
│  │ .md .html   │   │ 按标题切分  │   │ Embed API     │  │
│  │ .json .txt  │   │             │   │ → ChromaDB    │  │
│  └─────────────┘   └─────────────┘   └───────┬───────┘    │
│                                              │           │
│           ┌──────────────────────────────────┘            │
│           │                                              │
│           ▼                                              │
│    ┌──────────────┐     ┌─────────────┐                   │
│    │ 向量搜索     │     │ BM25 关键词 │                  │
│    │ (语义相似)   │     │ (精确匹配)  │                  │
│    └──────┬───────┘     └──────┬──────┘                   │
│           │                    │                          │
│           └────────┬───────────┘                          │
│                    ▼                                      │
│            ┌──────────────┐                               │
│            │ RRF 融合     │                               │
│            │ → 距离阈值   │                               │
│            │ → Top-20     │                               │
│            └──────────────┘                               │
└───────────────────────────────────────────────────────────┘
```

### 单次请求数据流

1. 用户输入问题 → `POST /api/chat`
2. **来源校验**——默认同源，或匹配精确配置的 Origin 白名单
3. **请求校验**——JSON 请求体上限 5 MiB；单条消息上限 4000 字符，历史最多 20 轮
4. **混合检索**——向量搜索（语义）+ BM25（关键词）→ RRF 融合 → 距离阈值过滤 → Top-20
5. **提示词组装**——人格 + 检索上下文 + 引用规则 + 安全护栏
6. **LLM 调用**——通过 OpenRouter 流式调用，自动模型切换
7. **流式响应**——token 逐字推送到前端
8. **追问建议**——回答完毕后生成 3 个相关问题

---

## 安全

| 层面 | 措施 |
|------|------|
| **浏览器访问** | 精确 Origin 白名单；`CORS_ORIGIN` 为空时仅允许同源浏览器请求 |
| **输入** | JSON 结构校验、5 MiB 请求体上限、4000 字符单条上限、20 轮历史限制 |
| **模型** | 护栏降低提示注入和越界回答风险，但不是安全边界 |
| **部署** | API Key 仅存储在服务端（`.env` 中的 `OPENROUTER_API_KEY`），绝不暴露给前端 |
| **重建** | 未设置 `REBUILD_SECRET` 时隐藏 `/api/rebuild-index`；设置后必须发送对应请求头 |

应用没有向模型提供网页浏览工具。系统提示会要求模型基于检索内容回答，但 LLM 的预训练知识不能被视为不可访问，也不能把提示词当作硬安全边界。

---

## 自定义配置

### 切换 AI 模型

```bash
# 默认：deepseek/deepseek-v4-flash
# 如需显式设置回退列表：
OPENROUTER_MODEL=deepseek/deepseek-v4-flash,google/gemini-2.5-flash
```

默认仅使用 DeepSeek V4 Flash。如需设置逗号分隔的回退列表，请在部署前到 [OpenRouter 模型目录](https://openrouter.ai/models) 验证每个 slug 当前可用。

### 切换嵌入模型

嵌入通过 OpenRouter API 完成——无需本地下载模型。默认为 `openai/text-embedding-3-small`（1536 维，每百万 token $0.02）。

在 `.env` 中指定：

```bash
EMBEDDING_MODEL=openai/text-embedding-3-small
```

| 模型 | 维度 | 价格/百万 token | 适用场景 |
|------|------|----------------|----------|
| `openai/text-embedding-3-small` | 1536 | $0.02 | 通用（默认） |
| `google/text-embedding-004` | 768 | $0.0025 | 低成本 |
| `cohere/embed-multilingual-v3.0` | 1024 | $0.10 | 多语言 |

### 调整检索策略

```bash
# .env
# 最终返回给 LLM 的 chunk 数（默认 20）
RETRIEVAL_K=20

# 向量和 BM25 各自检索的候选数（默认 50）
RETRIEVAL_CANDIDATE_K=50

# 余弦距离阈值——超过此值的 chunk 视为不相关，直接丢弃（默认 0.5）
# 越小越严格，设为 1.0 则关闭过滤
MIN_SIMILARITY=0.5
```

**检索管线**：
1. 向量搜索（语义相似）→ 取 CANDIDATE_K 个候选 → 距离阈值过滤
2. BM25 关键词搜索 → 取 CANDIDATE_K 个候选
3. Reciprocal Rank Fusion 融合两路排名 → 返回 Top-RETRIEVAL_K

知识库较小时（<100 个 chunk），建议设置 `MIN_SIMILARITY=1.0` 关闭过滤。知识库越大，阈值越重要。

### 自定义安全护栏

编辑 `backend/persona.py` 中的 `GUARDRAILS` 部分，调整：
- 来源扎根的严格程度
- 回答范围边界（AI 能/不能回答的内容）
- 回答长度默认值
- 语言行为

### 在线更新知识库

```bash
# 添加/修改文件后，重建索引：
curl -X POST http://localhost:8000/api/rebuild-index \
  -H "x-rebuild-secret: $REBUILD_SECRET"
```

先设置 `REBUILD_SECRET`；未设置时接口会刻意返回 404。无需重启。如果数据源是 GitHub 仓库，重建时会同步配置的稀疏检出；新索引构建失败时，旧索引仍保持可用。

### GitHub 数据源细节

当 `DATA_DIR` 指向 GitHub URL（如 `https://github.com/user/repo/tree/main/docs`）时：

1. **稀疏克隆**：`git clone --depth 1 --filter=blob:none --sparse`——仅拉取元数据和目标文件夹，不拉全仓库历史
2. **本地缓存**：按配置的仓库、ref 和路径缓存，重启后复用
3. **自动拉取**：重建时执行 `git pull --ff-only` 并刷新 sparse checkout 状态
4. **前提**：服务端需安装 `git`（大多数系统默认已有）

---

## API 参考

### `GET /api/health`

```json
{
  "status": "ok",
  "has_index": true,
  "chunk_count": 42,
  "has_bm25": true,
  "active_collection": "knowledge-staging-…",
  "retrieval_k": 20,
  "candidate_k": 50,
  "min_similarity": 0.5,
  "models": ["deepseek/deepseek-v4-flash"]
}
```

### `POST /api/chat`

请求：
```json
{
  "messages": [
    { "role": "user", "content": "你是做什么的？" }
  ],
  "sessionId": "abc123"
}
```

响应：流式 `text/plain` 正文。`X-RAG-Sources` 响应头以 JSON 形式提供至多三个检索来源标签。

### `POST /api/suggest`

请求格式与 chat 相同。

响应：
```json
{
  "suggestions": [
    "你用什么工具？",
    "你是怎么开始的？",
    "你最喜欢的项目是什么？"
  ]
}
```

### `POST /api/rebuild-index`

重建知识库索引。仅在配置 `REBUILD_SECRET` 且通过 `x-rebuild-secret` 请求头发送该密钥时可用；构建失败会保留当前活动索引。返回：`{ "status": "ok", "chunk_count": 42 }`。

---

## VPS 部署

架构简洁：一个 Docker 容器跑 FastAPI，前面挂一个反向代理提供 HTTPS。没有外部数据库依赖——ChromaDB 用 Docker volume 持久化，索引和缓存都在本地磁盘。

```
Internet ──▶ Nginx/Caddy (HTTPS) ──▶ Docker 容器 (FastAPI:8000)
```

### 前置条件

- **VPS**：Ubuntu 22.04+ / Debian 12+，1 核 1G 即可（推荐 2G，首次构建索引时嵌入 API 调用较多）
- **Docker + Docker Compose**：[官方安装指南](https://docs.docker.com/engine/install/)
- **域名**（推荐）：用于配置 HTTPS 证书
- **OpenRouter API Key**：[openrouter.ai](https://openrouter.ai/) 注册即送免费额度

### 步骤 1：准备项目

```bash
git clone https://github.com/zheminlin266/AI-RAG-site-chat.git
cd AI-RAG-site-chat

# 配置环境变量
cp .env.example .env
# 编辑 .env：填入 OPENROUTER_API_KEY
```

### 步骤 2：放入知识库文档

```bash
# 把你需要 AI"了解"的文档放进 knowledge-base/
cp /path/to/your/docs/*.md knowledge-base/
```

或通过 `.env` 设置 `DATA_DIR` 指向本地文件夹或 GitHub 仓库。

### 步骤 3：选择部署方案

下面对比三种方案，按复杂度递增：

| 方案 | HTTPS | 适合场景 |
|------|-------|---------|
| [A. 纯 Docker Compose](#方案-a纯-docker-compose) | 需额外配置 | 已有反向代理 / 仅测试 |
| [B. Docker + Caddy](#方案-bdocker--caddy推荐最简单-https) | 自动 | **推荐**：个人 VPS，最简单 |
| [C. Docker + Nginx + Let's Encrypt](#方案-cdocker--nginx--lets-encrypt) | 手动配置 | 已有 Nginx 或需要精细控制 |

---

### 方案 A：纯 Docker Compose

仅启动应用容器，监听 8000 端口。如果你已经有了反向代理或者只是想测试一下。

```bash
# 启动
docker compose up -d

# 检查状态
curl http://localhost:8000/api/health
# → {"status":"ok","has_index":true,"chunk_count":42,"has_bm25":true,"retrieval_k":20}

# 查看日志
docker compose logs -f
```

前端设置 `apiBase="http://your-server-ip:8000"`。如需 HTTPS，往下看。

---

### 方案 B：Docker + Caddy（推荐，最简单 HTTPS）

[Caddy](https://caddyserver.com/) 自动申请和续期 Let's Encrypt 证书，零配置 HTTPS。

**1. 安装 Caddy**

```bash
# Ubuntu/Debian
sudo apt install -y debian-keyring debian-archive-keyring apt-transport-https
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' | sudo tee /etc/apt/sources.list.d/caddy-stable.list
sudo apt update && sudo apt install caddy
```

**2. 启动应用**

```bash
docker compose up -d
# 应用绑定在 127.0.0.1:8000，外部无法直接访问
```

**3. 配置 Caddy**

编辑 `/etc/caddy/Caddyfile`：

```caddy
chat.your-domain.com {
    reverse_proxy 127.0.0.1:8000
}
```

```bash
sudo systemctl reload caddy
# 证书自动申请，几秒后 https://chat.your-domain.com 即可访问
```

前端设置 `apiBase="https://chat.your-domain.com"`。Caddy 自动处理 TLS、HTTP→HTTPS 重定向和流式 HTTP 响应代理。

---

### 方案 C：Docker + Nginx + Let's Encrypt

适合已有 Nginx 或需要更精细控制的场景。

**1. 启动应用**

```bash
docker compose up -d
```

**2. 安装 Nginx + Certbot**

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
```

**3. 配置 Nginx**

创建 `/etc/nginx/sites-available/rag-chat`：

```nginx
server {
    listen 80;
    server_name chat.your-domain.com;
    client_max_body_size 5m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;

        # 无缓冲流式响应需要这些
        proxy_buffering off;
        proxy_cache off;
        chunked_transfer_encoding on;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # 保护重建索引接口
    location /api/rebuild-index {
        proxy_pass http://127.0.0.1:8000;
        # 可选：添加 IP 白名单或 basic auth
        # allow 你的办公IP;
        # deny all;
    }
}
```

关键配置说明：
- `proxy_buffering off` + `proxy_cache off` — 流式响应的必要条件
- `proxy_http_version 1.1` — 支持 keep-alive 和 chunked transfer

**4. 启用站点 + HTTPS**

```bash
sudo ln -s /etc/nginx/sites-available/rag-chat /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx

# 申请证书
sudo certbot --nginx -d chat.your-domain.com

# 证书每 90 天自动续期
```

---

### 数据持久化

`docker-compose.yml` 中定义了两个 named volume，容器重启不会丢失数据：

| Volume | 路径 | 内容 |
|--------|------|------|
| `chroma_data` | `/app/.chroma_db` | 向量索引（首次启动自动构建） |
| `github_cache` | `/app/.github_cache` | GitHub 数据源缓存 |

知识库文档通过 bind mount 挂载（`./knowledge-base:/app/knowledge-base:ro`），宿主机直接编辑即可。

### 更新流程

```bash
# 拉取最新代码
git pull

# 重新构建并重启
docker compose up -d --build

# 如果知识库有变更，重建索引
curl -X POST http://localhost:8000/api/rebuild-index \
  -H "x-rebuild-secret: $REBUILD_SECRET"
```

### 日志与监控

```bash
# 实时日志
docker compose logs -f

# 健康检查
curl https://chat.your-domain.com/api/health

# 系统资源
docker stats rag-chat
```

推荐配合 [Uptime Kuma](https://github.com/louislam/uptime-kuma) 监控 `/api/health` 端点，或设置简单的 cron：

```bash
# crontab -e
*/5 * * * * curl -fSs https://chat.your-domain.com/api/health || echo "RAG Chat is down" | mail -s "Alert" you@example.com
```

### 安全建议

- 防火墙仅开放 80/443，**不要**开放 8000
- `.env` 中设置 `CORS_ORIGIN=https://your-domain.com`
- 仅把直接、可信的反向代理填写到 `TRUSTED_PROXY_IPS`；否则会忽略转发 IP/协议头
- 设置 `REBUILD_SECRET`；未设置时重建路由保持隐藏，也可在 nginx 通过 IP 白名单继续限制
- 定期 `docker compose pull` 更新基础镜像（安全补丁）

---

## 项目结构

```
AI-RAG-site-chat/
├── README.md
├── README.zh-CN.md
├── LICENSE
├── PERSONA.md              # AI 人格设定（编辑这个）
├── .env.example            # 配置模板
├── requirements.txt        # Python 依赖 (FastAPI, ChromaDB, rank-bm25...)
├── package.json
├── Dockerfile              # 容器镜像
├── docker-compose.yml      # VPS 一键部署
├── .dockerignore
│
├── backend/
│   ├── server.py           # FastAPI 服务（4 个接口）
│   ├── rag_engine.py       # RAG 管线（加载 → 切片 → 嵌入 → 混合检索）
│   ├── persona.py          # 加载 PERSONA.md，构建系统提示词
│   ├── chat_util.py        # 来源校验、消息清洗、HTTP 客户端、速率限制
│   ├── config.py           # 全部通过环境变量配置（含检索参数）
│   ├── github_source.py    # GitHub 仓库文件夹克隆与缓存
│   └── parsers/
│       ├── md_loader.py    # Markdown 解析器
│       ├── html_loader.py  # HTML 解析器（BeautifulSoup）
│       ├── json_loader.py  # JSON 结构化数据解析器
│       └── txt_loader.py   # 纯文本解析器
│
├── frontend/
│   ├── README.md           # React 与静态网站接入说明
│   ├── ai-chat.tsx         # React 聊天组件
│   └── standalone/
│       └── ai-rag-chat.js  # 零依赖 Web Component bundle
│
└── knowledge-base/         # 把你的文档放在这里
    └── .gitkeep
```

---

## 致谢

灵感来自 [pedromello.cc](https://pedromello.cc) 的 "Ask me anything" 模块。基于 [FastAPI](https://fastapi.tiangolo.com/)、[ChromaDB](https://www.trychroma.com/)、[rank-bm25](https://github.com/dorianbrown/rank_bm25) 和 [OpenRouter](https://openrouter.ai/)（LLM + 嵌入）构建。

---

## 许可证

[MIT](./LICENSE)——随便用，随便改，随便发。
