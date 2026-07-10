"""Application configuration and startup-time validation."""
from __future__ import annotations

import ipaddress
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv


class ConfigError(RuntimeError):
    """Raised when an environment value would make the service unsafe or invalid."""


def _env_int(name: str, default: int, *, minimum: int | None = None) -> int:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}")
    return value


def _env_float(
    name: str,
    default: float,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    raw = os.getenv(name, str(default)).strip()
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if minimum is not None and value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}")
    if maximum is not None and value > maximum:
        raise ConfigError(f"{name} must be at most {maximum}, got {value}")
    return value


def _normalise_config_origin(value: str) -> str:
    """Return a canonical http(s) origin, accepting a harmless trailing slash."""
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ConfigError(f"Invalid CORS origin {value!r}") from exc

    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ConfigError(
            f"CORS origin must be an http(s) origin without a path: {value!r}"
        )

    host = parsed.hostname.lower()
    if ":" in host:  # IPv6 literals need brackets in a URL.
        host = f"[{host}]"
    default_port = 443 if parsed.scheme == "https" else 80
    port_suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{parsed.scheme}://{host}{port_suffix}"


def _cors_origins(raw: str) -> tuple[str, ...]:
    origins: list[str] = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        if value == "*":
            raise ConfigError(
                "CORS_ORIGIN must list explicit origins; '*' disables origin protection."
            )
        canonical = _normalise_config_origin(value)
        if canonical not in origins:
            origins.append(canonical)
    return tuple(origins)


def _trusted_proxy_ips(raw: str) -> tuple[str, ...]:
    values: list[str] = []
    for item in raw.split(","):
        value = item.strip()
        if not value:
            continue
        try:
            ipaddress.ip_network(value, strict=False)
        except ValueError as exc:
            raise ConfigError(
                f"TRUSTED_PROXY_IPS must contain IP addresses or CIDRs, got {value!r}"
            ) from exc
        values.append(value)
    return tuple(values)


BASE_DIR = Path(__file__).resolve().parent.parent
_dotenv_path = BASE_DIR / ".env"
if _dotenv_path.exists():
    load_dotenv(_dotenv_path)
else:
    load_dotenv()


# Paths
PERSONA_FILE = Path(os.getenv("PERSONA_FILE", str(BASE_DIR / "PERSONA.md")))
GITHUB_CACHE_DIR = Path(os.getenv("GITHUB_CACHE_DIR", str(BASE_DIR / ".github_cache")))

_data_dir_env = os.getenv("DATA_DIR", "").strip()
RAW_DATA_DIR = _data_dir_env
if _data_dir_env:
    from backend.github_source import is_github_url

    if is_github_url(_data_dir_env):
        # Replaced with the checked-out directory during application startup.
        KNOWLEDGE_BASE_DIR = BASE_DIR / "knowledge-base"
    else:
        KNOWLEDGE_BASE_DIR = Path(_data_dir_env)
        if not KNOWLEDGE_BASE_DIR.is_absolute():
            KNOWLEDGE_BASE_DIR = BASE_DIR / KNOWLEDGE_BASE_DIR
else:
    KNOWLEDGE_BASE_DIR = Path(
        os.getenv("KNOWLEDGE_BASE_DIR", str(BASE_DIR / "knowledge-base"))
    )

CHROMA_DB_DIR = BASE_DIR / ".chroma_db"


# RAG
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "openai/text-embedding-3-small").strip()
if not EMBEDDING_MODEL:
    raise ConfigError("EMBEDDING_MODEL must not be empty")

CHUNK_SIZE = _env_int("CHUNK_SIZE", 500, minimum=1)
CHUNK_OVERLAP = _env_int("CHUNK_OVERLAP", 50, minimum=0)
if CHUNK_OVERLAP >= CHUNK_SIZE:
    raise ConfigError("CHUNK_OVERLAP must be smaller than CHUNK_SIZE")

RETRIEVAL_K = _env_int("RETRIEVAL_K", 20, minimum=1)
RETRIEVAL_CANDIDATE_K = _env_int("RETRIEVAL_CANDIDATE_K", 50, minimum=1)
if RETRIEVAL_CANDIDATE_K < RETRIEVAL_K:
    raise ConfigError("RETRIEVAL_CANDIDATE_K must be at least RETRIEVAL_K")
MIN_SIMILARITY = _env_float("MIN_SIMILARITY", 0.5, minimum=0.0, maximum=2.0)


# LLM
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "").strip()
DEFAULT_MODELS = ["deepseek/deepseek-v4-flash"]
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "")
MAX_TOKENS = _env_int("MAX_TOKENS", 1024, minimum=1)
TEMPERATURE = _env_float("TEMPERATURE", 0.6, minimum=0.0, maximum=2.0)
SUGGEST_MAX_TOKENS = _env_int("SUGGEST_MAX_TOKENS", 200, minimum=1)
SUGGEST_TEMPERATURE = _env_float("SUGGEST_TEMPERATURE", 0.7, minimum=0.0, maximum=2.0)


# Security and request limits
# 20 conversation turns means at most 40 user/assistant messages.
MAX_HISTORY = 40
MAX_CHARS = _env_int("MAX_CHARS", 4000, minimum=1)
MAX_REQUEST_BODY_BYTES = 5 * 1024 * 1024

# Empty means same-origin only. Cross-origin deployments must opt in explicitly.
CORS_ORIGINS = _cors_origins(os.getenv("CORS_ORIGIN", ""))
CORS_ORIGIN = ",".join(CORS_ORIGINS)

# X-Forwarded-For is honored only when the direct peer is in this explicit list.
TRUSTED_PROXY_IPS = _trusted_proxy_ips(os.getenv("TRUSTED_PROXY_IPS", ""))

RATE_LIMIT_CHAT = (
    _env_int("RATE_LIMIT_CHAT_MAX", 20, minimum=1),
    _env_int("RATE_LIMIT_CHAT_WINDOW", 60, minimum=1),
)
RATE_LIMIT_SUGGEST = (
    _env_int("RATE_LIMIT_SUGGEST_MAX", 30, minimum=1),
    _env_int("RATE_LIMIT_SUGGEST_WINDOW", 60, minimum=1),
)
RATE_LIMIT_REBUILD = (
    _env_int("RATE_LIMIT_REBUILD_MAX", 3, minimum=1),
    _env_int("RATE_LIMIT_REBUILD_WINDOW", 300, minimum=1),
)
MAX_CONCURRENT_LLM = _env_int("MAX_CONCURRENT_LLM", 5, minimum=1)

# Leaving this empty intentionally disables the public rebuild endpoint.
REBUILD_SECRET = os.getenv("REBUILD_SECRET", "")


# Server
PORT = _env_int("PORT", 8000, minimum=1)
if PORT > 65535:
    raise ConfigError("PORT must be at most 65535")


def models() -> list[str]:
    configured = [m.strip() for m in OPENROUTER_MODEL.split(",") if m.strip()]
    return configured or DEFAULT_MODELS[:]


def ensure_dirs() -> None:
    KNOWLEDGE_BASE_DIR.mkdir(parents=True, exist_ok=True)
    CHROMA_DB_DIR.mkdir(parents=True, exist_ok=True)
