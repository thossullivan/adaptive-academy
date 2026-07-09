# --- Stage 1: build the SvelteKit SPA ---------------------------------------
FROM node:22-slim AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- Stage 2: Python runtime -------------------------------------------------
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.7 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Dependencies first (cache-friendly), project second.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

COPY --from=frontend /fe/build ./frontend/build
COPY docker/entrypoint.sh /entrypoint.sh

ENV PATH="/app/.venv/bin:$PATH" \
    AA_FRONTEND_DIST=/app/frontend/build \
    AA_DATABASE_URL=sqlite:////data/adaptive_academy.db
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
