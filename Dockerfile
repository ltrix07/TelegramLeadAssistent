FROM ghcr.io/astral-sh/uv:0.11.21 AS uv

FROM python:3.12.13-slim-bookworm AS base

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

RUN useradd --create-home --uid 10001 app \
    && install -d -o app -g app /sessions

WORKDIR /app

COPY --from=uv /uv /uvx /bin/
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
COPY scripts ./scripts
COPY alembic.ini ./
COPY alembic ./alembic

FROM base AS development

RUN uv sync --frozen --all-groups --no-install-project
COPY tests ./tests

USER app

CMD ["pytest"]

FROM base AS runtime

USER app

CMD ["python", "-m", "app.maintenance"]

FROM base AS translation-manager

USER root
RUN useradd --create-home --uid 1032 translation-manager \
    && uv pip install "argos-translate-lt==1.12.1"
USER translation-manager

CMD ["python", "-m", "app.translation.manager"]
