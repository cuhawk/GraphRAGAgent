# NexusGraph API server (single image; profile selected via env).
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# uv for fast, lockfile-exact installs
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install dependencies first (layer cache)
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project

# Install the application
COPY src ./src
COPY ontology ./ontology
RUN uv sync --frozen --no-dev

# The synthetic dataset is generated at startup (bootstrap_on_start=true).
ENV NEXUSGRAPH_DATA_DIR=/app/data
VOLUME ["/app/data"]

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s \
  CMD ["uv", "run", "python", "-c", \
       "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status == 200 else 1)"]

CMD ["uv", "run", "uvicorn", "nexusgraph.api.app:create_app", \
     "--factory", "--host", "0.0.0.0", "--port", "8000"]
