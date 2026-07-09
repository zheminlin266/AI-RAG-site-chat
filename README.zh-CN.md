# RAG Site Chat

**基于 RAG 的 AI 聊天组件，适用于任意静态网站。** 放入你的文档，编写人格设定，填入你的 API Key——网站访客即可在 5 分钟内与你的内容对话。

<p align="center">
  <img src="https://img.shields.io/badge/python-3.10+-blue.svg" alt="Python 3.10+">
  <img src="https://img.shields.io/badge/license-MIT-green.svg" alt="License: MIT">
  <img src="https://img.shields.io/badge/backend-FastAPI-009688?logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/vector_db-ChromaDB-FF6F00" alt="ChromaDB">
  <img src="https://img.shields.io/badge/llm-OpenRouter-6366f1" alt="OpenRouter">
  <img src="https://img.shields.io/badge/frontend-React_18-61DAFB?logo=react" alt="React">
</p>

> 英文原版: [README.md](./README.md)

---

## 它能做什么

网站右下角出现一个浮动聊天按钮。访客点击后提问，得到的回答基于**你的**内容——你的博客、文档、数据。AI 只知道你给它的东西。

- **RAG（检索增强生成）**：回答扎根于你的文档，拒绝幻觉
- **多格式支持**：Markdown、HTML、JSON、纯文本——直接丢进去
- **API 嵌入**：无需本地下载模型，全部通过 OpenRouter 接口
- **流式响应**：文字逐字生成，所见即所得
- **模型自动切换**：一个 LLM 挂了，自动尝试下一个
- **追问建议**：让对话持续下去
- **同源保护**：只有你的网站才能调用 API
- **GitHub 数据源**：指向任意公开仓库的文件夹——自动克隆与同步

---

## 快速开始

### 1. 克隆并安装

```bash
git clone https://github.com/your-org/AI-RAG-site-chat.git
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

### 6. 在你的网站上添加聊天组件

在你的 React / Next.js 应用中引入 `<AiChat />`：

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

或者以原生脚本方式嵌入（详见 [frontend/README.md](./frontend/README.md)）。

---

## 架构

```
┌─────────────────────────────────────────────────────────┐
│                    你的网站                               │
│  ┌──────────────────────────────────────────────────┐   │
│  │            ai-chat.tsx（聊天组件）                 │   │
│  │  · 浮动按钮 → 聊天面板                            │   │
│  │  · 流式逐字渲染                                    │   │
│  │  · 会话管理                                       │   │
│  │  · 追问建议                                       │   │
│  └─────────────┬────────────────────────────────────┘   │
│                │ POST /api/chat                          │
└────────────────┼────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│             server.py (FastAPI)                           │
│                                                           │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐   │
│  │ 来源校验 │  │ 消息清洗 │  │ 流式响应 (SSE)        │   │
│  └──────────┘  └──────────┘  └──────────────────────┘   │
│        │              │               │                   │
│  ┌─────▼──────────────▼───────────────▼──────────────┐   │
│  │              处理管线                              │   │
│  │  人格 (PERSONA.md) + RAG 上下文 + 安全护栏        │   │
│  └──────────────────────┬────────────────────────────┘   │
│                         │                                 │
│  ┌──────────────────────▼────────────────────────────┐   │
│  │            OpenRouter API 调用                     │   │
│  │  模型1 → 失败？→ 模型2 → 失败？→ 报错            │   │
│  └───────────────────────────────────────────────────┘   │
└───────────────────────────────────────────────────────────┘
                 │
┌────────────────▼────────────────────────────────────────┐
│              rag_engine.py (RAG 引擎)                     │
│                                                           │
│  数据来源: 本地文件夹 │ GitHub 仓库 │ knowledge-base/     │
│  ┌─────────────┐   ┌─────────────┐   ┌───────────────┐  │
│  │ 文档加载器  │──▶│ 切片器      │──▶│ OpenRouter    │  │
│  │ .md .html   │   │ 按标题切分  │   │ Embed API     │  │
│  │ .json .txt  │   │             │   │ → ChromaDB    │  │
│  └─────────────┘   └─────────────┘   └───────┬───────┘  │
│                                              │           │
│                    用户提问 → Embed API → Top-K 搜索      │
└──────────────────────────────────────────────────────────┘
```

### 单次请求数据流

1. 用户输入问题 → `POST /api/chat`
2. **来源校验**——仅允许同源请求
3. **消息清洗**——单条上限 4000 字符，历史最多 20 轮
4. **RAG 检索**——问题嵌入后从 ChromaDB 取 Top-5 相关片段
5. **提示词组装**——人格 + 检索上下文 + 引用规则 + 安全护栏
6. **LLM 调用**——通过 OpenRouter 流式调用，自动模型切换
7. **流式响应**——token 逐字推送到前端
8. **追问建议**——回答完毕后生成 3 个相关问题

---

## 安全

| 层面 | 措施 |
|------|------|
| **传输** | Origin 头校验——只有你的域名才能调用 API |
| **输入** | 消息类型校验、4000 字符上限、20 轮历史限制 |
| **模型** | 安全护栏提示词防止越狱、幻觉、越界回答 |
| **部署** | API Key 仅存储在服务端（`.env` 中的 `OPENROUTER_API_KEY`），绝不暴露给前端 |
| **CORS** | 可配置 `CORS_ORIGIN`——生产环境限制到你的域名 |

AI **无法**访问互联网、训练数据、或知识库之外的任何内容。它只知道你给它的东西。

---

## 自定义配置

### 切换 AI 模型

```bash
# .env
OPENROUTER_MODEL=deepseek/deepseek-v4-flash,google/gemini-2.0-flash-001
```

默认：DeepSeek V4 Flash → Gemini Flash 回退。任意 [OpenRouter 模型](https://openrouter.ai/models) 都可用。

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

### 自定义安全护栏

编辑 `backend/persona.py` 中的 `GUARDRAILS` 部分，调整：
- 来源扎根的严格程度
- 回答范围边界（AI 能/不能回答的内容）
- 回答长度默认值
- 语言行为

### 在线更新知识库

```bash
# 添加/修改文件后，重建索引：
curl -X POST http://localhost:8000/api/rebuild-index
```

无需重启。如果数据源是 GitHub 仓库，重建索引时还会自动 `git pull` 获取最新内容。

### GitHub 数据源细节

当 `DATA_DIR` 指向 GitHub URL（如 `https://github.com/user/repo/tree/main/docs`）时：

1. **稀疏克隆**：`git clone --depth 1 --filter=blob:none --sparse`——仅拉取元数据和目标文件夹，不拉全仓库历史
2. **本地缓存**：存储在 `.github_cache/{owner}_{repo}/`，重启后复用
3. **自动拉取**：重建索引时执行 `git pull --ff-only` 获取最新改动
4. **前提**：服务端需安装 `git`（大多数系统默认已有）

---

## API 参考

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

请求：
```json
{
  "messages": [
    { "role": "user", "content": "你是做什么的？" }
  ],
  "sessionId": "abc123"
}
```

响应：`text/plain` 流式，逐 token 推送。

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

重建知识库索引。返回：`{ "status": "ok", "chunk_count": 42 }`

---

## 部署

### 方式 A：Nginx 反向代理（推荐）

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000;
    proxy_buffering off;
    proxy_cache off;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
}
```

前端设置 `apiBase="/api"`——同源访问，无 CORS 问题。

### 方式 B：Docker

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY . .
CMD ["python", "-m", "backend.server"]
```

### 方式 C：GitHub Pages + 独立后端

静态站点托管在 GitHub Pages，后端跑在 $5/月的 VPS 或 [Fly.io](https://fly.io) / [Railway](https://railway.app)。在 `.env` 中设置 `CORS_ORIGIN=https://your-site.github.io`。

---

## 项目结构

```
AI-RAG-site-chat/
├── README.md
├── PERSONA.md              # AI 人格设定（编辑这个）
├── .env.example            # 配置模板
├── requirements.txt
├── package.json
│
├── backend/
│   ├── server.py           # FastAPI 服务（4 个接口）
│   ├── rag_engine.py       # RAG 管线（加载 → 切片 → 嵌入 → 搜索）
│   ├── persona.py          # 加载 PERSONA.md，构建系统提示词
│   ├── chat_util.py        # 来源校验、消息清洗、HTTP 客户端、速率限制
│   ├── config.py           # 全部通过环境变量配置
│   ├── github_source.py    # GitHub 仓库文件夹克隆与缓存
│   └── parsers/
│       ├── md_loader.py    # Markdown 解析器
│       ├── html_loader.py  # HTML 解析器（BeautifulSoup）
│       ├── json_loader.py  # JSON 结构化数据解析器
│       └── txt_loader.py   # 纯文本解析器
│
├── frontend/
│   └── ai-chat.tsx         # React 聊天组件（887 行）
│
└── knowledge-base/         # 把你的文档放在这里
    └── .gitkeep
```

---

## 致谢

灵感来自 [pedromello.cc](https://pedromello.cc) 的 "Ask me anything" 模块。基于 [FastAPI](https://fastapi.tiangolo.com/)、[ChromaDB](https://www.trychroma.com/) 和 [OpenRouter](https://openrouter.ai/)（LLM + 嵌入）构建。

---

## 许可证

MIT——随便用，随便改，随便发。
