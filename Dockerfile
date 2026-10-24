# syntax=docker/dockerfile:1

# ---- 1. Build the React UI -------------------------------------------------
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---- 2. Python app: API + MCP + analysis pipeline -------------------------
FROM python:3.12-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg ca-certificates \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.4 /uv /usr/local/bin/uv

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    INSTAMCP_DATA_DIR=/data \
    INSTAMCP_WEB_DIST=/app/web/dist \
    HF_HOME=/data/models \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
# Dependencies first so code changes don't reinstall them.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project --extra decisions
COPY src ./src
RUN uv sync --frozen --no-dev --extra decisions
COPY --from=web /web/dist ./web/dist

VOLUME /data
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/api/health')"

CMD ["instamcp", "web", "--host", "0.0.0.0", "--port", "8080"]
