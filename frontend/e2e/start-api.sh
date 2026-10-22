#!/usr/bin/env sh
# Start a throwaway API for the Playwright e2e run: fresh db, real migrations, a
# deterministic seed, and no LLM key (no test may spend tokens).
set -e
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(cd "$here/../.." && pwd)"
tmp="$here/.tmp"
mkdir -p "$tmp"
# The screenshot run (playwright.screenshots.config.ts) reuses this script with its own db
# name and seed, so it never shares a db with a concurrent e2e run.
db="${E2E_DB_NAME:-e2e.db}"
seed="${E2E_SEED_SCRIPT:-$here/seed_e2e.py}"
rm -f "$tmp/$db" "$tmp/$db-wal" "$tmp/$db-shm"

# Settings fall back to the repo .env for any AA_ variable left unset, so pin every one
# explicitly; otherwise a developer's real vault or embedding cache would leak into the run.
unset ANTHROPIC_API_KEY OPENROUTER_API_KEY AA_LLM_BACKEND
export AA_DATABASE_URL="sqlite:///$tmp/$db"
export AA_RETRIEVER=fts
export AA_FRONTEND_DIST="$tmp/no-frontend-build"
export AA_OBSIDIAN_VAULT_PATH=""
export AA_EMBEDDING_CACHE_DIR="$tmp/fastembed_cache"
export AA_EMBEDDING_ALLOW_DOWNLOAD=false
export AA_EMBEDDING_MODEL="BAAI/bge-small-en-v1.5"
export AA_DAILY_BUDGET_USD="${E2E_DAILY_BUDGET_USD:-}"

cd "$repo"
uv run alembic upgrade head
uv run python "$seed"
exec uv run uvicorn adaptive_academy.api.app:app --host 127.0.0.1 --port "${E2E_API_PORT:-18765}"
