"""
RAG Site Chat — 配置中心。所有参数通过环境变量覆盖默认值。
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# ── 加载 .env ──────────────────────────────────────
BASE_DIR = Path(__file__).resolve().parent.parent
_dotenv_path = BASE_DIR / ".env"
if _dotenv_path.exists():
    load_dotenv(_dotenv_path)
else:
    load_dotenv()  # fallback: search cwd

# ── 路径 ───────────────────────────────────────────
PERSONA_FILE = Path(os.getenv("PERSONA_FILE", str(BASE_DIR / "PERSONA.md")))

# GitHub 仓库缓存目录
GITHUB_CACHE_DIR = Path(os.getenv("GITHUB_CACHE_DIR", str(BASE_DIR / ".github_cache")))

# DATA_DIR: 指向外部数据文件夹或 GitHub 仓库 URL
#   本地路径: DATA_DIR=D:\Projects\my-site\docs
#   GitHub:   DATA_DIR=https://github.com/user/repo/tree/main/docs
_data_dir_env = os.getenv("DATA_DIR", "")

# 运行时解析：GitHub URL 在服务器 lifespan 中处理
# 这里只存入原始值，供 server.py 读取
RAW_DATA_DIR = _data_dir_env

if _data_dir_env:
    from backend.github_source import is_github_url
    if is_github_url(_data_dir_env):
        # GitHub URL: 由 server.py 的 lifespan 处理 clone
        # 临时指向一个占位路径，启动后替换
        KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge-base"
    else:
        KNOWLEDGE_BASE_DIR = Path(_data_dir_env)
        if not KNOWLEDGE_BASE_DIR.is_absolute():
            KNOWLEDGE_BASE_DIR = BASE_DIR / KNOWLEDGE_BASE_DIR
else:
    KNOWLEDGE_BASE_DIR = Path(os.getenv("KNOWLEDGE_BASE_DIR", str(BASE_DIR / "knowledge-base")))

CHROMA_DB_DIR = BASE_DIR / ".chroma_db"

# ── RAG ────────────────────────────────────────────
# 嵌入模型 — 通过 OpenRouter API（无需本地下载）
# openai/text-embedding-3-small: 1536维, $0.02/1M tokens
# 备选: google/text-embedding-004, cohere/embed-multilingual-v3.0
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", "50"))

# 检索参数
# RETRIEVAL_K: 最终返回给 LLM 的 chunk 数
# CANDIDATE_K: 向量/BM25 各自检索的候选数（应 >= RETRIEVAL_K）
# MIN_SIMILARITY: 余弦距离阈值（越小越相似），超过此值的 chunk 视为不相关
RETRIEVAL_K = int(os.getenv("RETRIEVAL_K", "20"))
RETRIEVAL_CANDIDATE_K = int(os.getenv("RETRIEVAL_CANDIDATE_K", "50"))
MIN_SIMILARITY = float(os.getenv("MIN_SIMILARITY", "0.5"))

# ── LLM ────────────────────────────────────────────
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

DEFAULT_MODELS = [
    "deepseek/deepseek-v4-flash",
    "google/gemini-2.0-flash-001",
]

OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "")

MAX_TOKENS = 1024
TEMPERATURE = 0.6
SUGGEST_MAX_TOKENS = 200
SUGGEST_TEMPERATURE = 0.7

# ── 安全 ───────────────────────────────────────────
MAX_HISTORY = 20
MAX_CHARS = 4000
CORS_ORIGIN = os.getenv("CORS_ORIGIN", "*")

# 频率限制: (最大请求数, 时间窗口秒)
RATE_LIMIT_CHAT = (
    int(os.getenv("RATE_LIMIT_CHAT_MAX", "20")),
    int(os.getenv("RATE_LIMIT_CHAT_WINDOW", "60")),
)
RATE_LIMIT_SUGGEST = (
    int(os.getenv("RATE_LIMIT_SUGGEST_MAX", "30")),
    int(os.getenv("RATE_LIMIT_SUGGEST_WINDOW", "60")),
)
RATE_LIMIT_REBUILD = (
    int(os.getenv("RATE_LIMIT_REBUILD_MAX", "3")),
    int(os.getenv("RATE_LIMIT_REBUILD_WINDOW", "300")),
)

# 并发限制: 同时进行的 LLM 调用上限
MAX_CONCURRENT_LLM = int(os.getenv("MAX_CONCURRENT_LLM", "5"))

# 重建索引的简单密钥（生产环境建议用 nginx basic auth 替代）
REBUILD_SECRET = os.getenv("REBUILD_SECRET", "")

# ── 服务 ───────────────────────────────────────────
PORT = int(os.getenv("PORT", "8000"))


def models() -> list[str]:
    env = OPENROUTER_MODEL.strip()
    if env:
        return [m.strip() for m in env.split(",") if m.strip()]
    return DEFAULT_MODELS


def ensure_dirs() -> None:
    KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
