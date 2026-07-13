FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim AS base

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

COPY pyproject.toml uv.lock ./

FROM base AS development

RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH"

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic
COPY tests ./tests

CMD ["sh", "-c", "uv run alembic upgrade head && uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000"]

FROM base AS runtime

RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

COPY app ./app
COPY alembic.ini ./
COPY alembic ./alembic

CMD ["sh", "-c", "uv run alembic upgrade head && uv run --no-sync uvicorn app.main:app --host 0.0.0.0 --port 8000"]
