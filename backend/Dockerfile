# syntax=docker/dockerfile:1

# ---- Builder: resolve and install production dependencies into a venv ----
# Same Python minor as CI and .python-version.
FROM python:3.14-slim AS builder

WORKDIR /app

# Build toolchain is only needed to compile any sdists during the install; it stays
# out of the runtime image below.
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

# Install runtime dependencies only. --no-default-groups skips dev tooling and the
# `local-ai` group (fastembed + onnxruntime): production embeds through a hosted API
# (EMBEDDING__PROVIDER=cloudflare), which keeps the image and RAM small. --frozen fails
# the build if uv.lock is out of sync with pyproject.toml.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-default-groups

# ---- Runtime: slim image carrying just the venv + application code ----
FROM python:3.14-slim AS runtime

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    PATH="/app/.venv/bin:$PATH" \
    WEB_CONCURRENCY=1

# Unprivileged runtime user (the entrypoint drops to it after preparing /data).
RUN groupadd --system app && useradd --system --gid app --home-dir /app app

# Bring in the prebuilt virtualenv from the builder (no build tools in this layer).
COPY --from=builder /app/.venv /app/.venv

# Application code (migrations + scripts included; tests/local DB/.env excluded via .dockerignore).
COPY . .

RUN chmod +x docker-entrypoint.sh && mkdir -p uploads && chown -R app:app /app

EXPOSE 8000

ENTRYPOINT ["./docker-entrypoint.sh"]

# Production server: no --reload. Exactly one worker per container is required -- the
# WebSocket fan-out, the in-memory rate limiter, and embedded Qdrant all keep state in
# this process. Local dev re-enables --reload via docker-compose.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
