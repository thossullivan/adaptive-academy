# --- Stage 1: build the SvelteKit SPA ---------------------------------------
# The SPA build is CPU-independent, so run it natively even when building arm64 on amd64.
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend
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
RUN uv sync --frozen --no-dev --no-install-project --extra memory
COPY src ./src
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev --extra memory

COPY --from=frontend /fe/build ./frontend/build
COPY docker/entrypoint.sh /entrypoint.sh

# The app runs as an unprivileged user. The image (/app) stays root-owned and read-only to
# it; only /data (the db + embedding cache volume) and /vault are written. The entrypoint
# starts as root just long enough to hand /data to AA_UID:AA_GID (volumes created by older,
# root-running images are root-owned), then drops privileges with setpriv (util-linux).
RUN groupadd --gid 1000 app \
 && useradd --uid 1000 --gid app --home-dir /home/app --create-home --shell /usr/sbin/nologin app \
 && mkdir -p /data && chown app:app /data

ENV PATH="/app/.venv/bin:$PATH" \
    HOME=/home/app \
    AA_UID=1000 \
    AA_GID=1000 \
    AA_FRONTEND_DIST=/app/frontend/build \
    AA_DATABASE_URL=sqlite:////data/adaptive_academy.db
EXPOSE 8000
ENTRYPOINT ["/entrypoint.sh"]
