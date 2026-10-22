# ==========================================
# Stage 1: Build virtual environment with uv
# ==========================================
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS builder

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

# Cache dependency layer
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Copy application and sync project
COPY . /app
RUN uv sync --frozen --no-dev

# ==========================================
# Stage 2: Minimal Production Runtime
# ==========================================
FROM python:3.12-slim-bookworm AS runtime

# Install system runtime libraries (libpq for PostgreSQL, curl for health checks,
# gosu to drop root privileges after fixing volume permissions at startup)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libpq5 \
    gosu \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN groupadd -g 1000 appuser && \
    useradd -u 1000 -g appuser -s /bin/bash -m appuser

WORKDIR /app

# Copy virtualenv and code from builder
COPY --from=builder --chown=appuser:appuser /app/.venv /app/.venv
COPY --chown=appuser:appuser . /app
RUN chmod +x /app/docker-entrypoint.sh

# Set runtime environment
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DOCKER_CONTAINER=true

# Stay as root at container start: the entrypoint fixes ownership of any
# volume mounted over /app/staticfiles (fresh volumes are created root-owned,
# which shadows the --chown above) before dropping to appuser via gosu.
EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "3", "--timeout", "120", "config.wsgi:application"]
