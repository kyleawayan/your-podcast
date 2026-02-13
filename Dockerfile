# ==========================================================
# Stage 1: Builder — install dependencies with uv
# ==========================================================
FROM ghcr.io/astral-sh/uv:0.6-python3.12-bookworm-slim AS builder

WORKDIR /app

# Copy dependency files first for layer caching
COPY pyproject.toml uv.lock ./

# Install dependencies from lockfile, excluding packages that are
# heavy and incompatible with headless ARM64 (torch ~2GB).
# playwright Python package is kept (podcastfy imports it) but browser
# binaries are not installed. Safe because generator.py lazy-imports
# chatterbox which pulls in torch.
RUN uv sync --frozen --no-install-project \
    --no-install-package chatterbox-tts \
    --no-install-package torch \
    --no-install-package torchaudio \
    --no-install-package torio

# Copy source and install the project itself
COPY src/ src/
COPY alembic/ alembic/
COPY alembic.ini ./

RUN uv sync --frozen \
    --no-install-package chatterbox-tts \
    --no-install-package torch \
    --no-install-package torchaudio \
    --no-install-package torio

# ==========================================================
# Stage 2: Runtime — slim image with only what's needed
# ==========================================================
FROM python:3.12-slim-bookworm

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy the virtual environment and app from builder
COPY --from=builder /app/.venv /app/.venv
COPY --from=builder /app/src /app/src
COPY --from=builder /app/alembic /app/alembic
COPY --from=builder /app/alembic.ini /app/alembic.ini
COPY --from=builder /app/pyproject.toml /app/pyproject.toml

ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

RUN mkdir -p /app/data/podcasts /app/data/transcripts

ENTRYPOINT ["your-podcast"]
CMD ["--help"]
