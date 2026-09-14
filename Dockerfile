# syntax=docker/dockerfile:1

FROM python:3.12-slim-bookworm

# Keep uv aligned with the version used to generate the project's lock file.
COPY --from=ghcr.io/astral-sh/uv:0.7.10 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HOME=/app \
    PATH="/app/.venv/bin:$PATH" \
    QSEARCH_DATABASES_ROOT=/app/databases \
    QSEARCH_QUEUE_ROOT=/app/data/queue

WORKDIR /app

# OpenCV, PyTorch and FAISS need these shared libraries at runtime.
RUN apt-get update \
    && apt-get install --yes --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system qsearch \
    && useradd --system --gid qsearch --home-dir /app --shell /usr/sbin/nologin qsearch

# Install locked third-party dependencies separately so source edits retain the
# expensive dependency layer (Torch, Transformers, FAISS, and model tooling).
COPY pyproject.toml uv.lock README.md ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY --chown=qsearch:qsearch src ./src
COPY --chown=qsearch:qsearch .streamlit ./.streamlit

# Keep the project editable so code that resolves models relative to the source
# tree continues to use /app/models.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev \
    && mkdir -p /app/.cache /app/databases /app/data/queue /app/models \
    && chown qsearch:qsearch /app \
    && chown -R qsearch:qsearch /app/.cache /app/databases /app/data /app/models

USER qsearch

EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8501/_stcore/health', timeout=3)" || exit 1

CMD ["streamlit", "run", "src/qsearch/webui/app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
