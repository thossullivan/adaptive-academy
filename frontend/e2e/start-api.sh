#!/usr/bin/env sh
# Start a throwaway API for the Playwright e2e run: fresh db, real migrations, a
# deterministic seed, and no LLM key (no test may spend tokens).
set -e
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
tmp="$here/.tmp"
mkdir -p "$tmp"
rm -f "$tmp"/e2e.db "$tmp"/e2e.db-wal "$tmp"/e2e.db-shm

# Settings fall back to the repo .env for any AA_ variable left unset, so pin every one
# explicitly; otherwise a developer's real vault or embedding cache would leak into the run.
unset ANTHROPIC_API_KEY AA_LLM_BACKEND
export AA_DATABASE_URL="sqlite:///$tmp/e2e.db"
export AA_RETRIEVER=fts
export AA_FRONTEND_DIST="$tmp/no-frontend-build"
export AA_OBSIDIAN_VAULT_PATH=""
export AA_EMBEDDING_CACHE_DIR="$tmp/fastembed_cache"
export AA_EMBEDDING_ALLOW_DOWNLOAD=false
export AA_EMBEDDING_MODEL="BAAI/bge-small-en-v1.5"
export AA_DAILY_BUDGET_USD=""

cd "$repo"
uv run alembic upgrade head
uv run python "$here/seed_e2e.py"
exec uv run uvicorn adaptive_academy.api.app:app --host 127.0.0.1 --port "${E2E_API_PORT:-18765}"
