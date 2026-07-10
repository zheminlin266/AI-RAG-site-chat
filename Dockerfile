FROM python:3.11-slim

LABEL org.opencontainers.image.title="RAG Site Chat"
LABEL org.opencontainers.image.description="RAG-powered AI chat widget backend"
LABEL org.opencontainers.image.source="https://github.com/zheminlin266/AI-RAG-site-chat"

WORKDIR /app

# git required for GitHub data source (sparse checkout)
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Create non-root user for runtime security
RUN useradd --create-home appuser \
    && mkdir -p /app/.chroma_db /app/.github_cache /app/knowledge-base \
    && chown -R appuser:appuser /app
USER appuser

ENV PORT=8000

# Use the app's own startup (respects PORT env var) instead of hardcoded uvicorn
CMD ["python", "-m", "backend.server"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD-SHELL python -c "from urllib.request import urlopen; urlopen('http://localhost:${PORT:-8000}/api/health')" || exit 1

EXPOSE 8000
