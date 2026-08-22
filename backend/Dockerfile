# syntax=docker/dockerfile:1
FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH=/opt/venv/bin:$PATH

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /usr/local/bin/uv

WORKDIR /app

# Dependencies first so a source-only change does not re-resolve the world.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY alembic.ini ./
COPY alembic ./alembic
COPY src ./src
RUN uv sync --frozen --no-dev

EXPOSE 8000

# Railway injects $PORT; default keeps `docker run` and compose usable unchanged.
CMD ["sh", "-c", "uvicorn vitals.api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
