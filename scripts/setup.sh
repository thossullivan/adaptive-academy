#!/usr/bin/env sh
# One-time local setup (`just setup`): check prerequisites, install Python and frontend
# dependencies, create the SQLite schema, and create .env from .env.example if missing.
# Safe to re-run. `--memory` also installs the optional hybrid-retrieval extra (sqlite-vec +
# fastembed); a plain re-run without it uninstalls that extra again, as `uv sync` does.
set -e

here="$(cd "$(dirname "$0")" && pwd)"
cd "$here/.."

extras=""
for arg in "$@"; do
	case "$arg" in
		--memory) extras="--extra memory" ;;
		*) echo "usage: just setup [--memory]" >&2; exit 2 ;;
	esac
done

say() { printf '\n==> %s\n' "$*"; }
missing=""
need() { missing="$missing\n  - $*"; }

# --- Prerequisites ----------------------------------------------------------
# Vite 8 (and the Svelte plugin) need Node ^20.19 or >=22.12; CI runs Node 22.
if ! command -v uv >/dev/null 2>&1; then
	need "uv (Python package manager): curl -LsSf https://astral.sh/uv/install.sh | sh
    (or see https://docs.astral.sh/uv/getting-started/installation/). uv also fetches Python 3.12."
fi
if command -v node >/dev/null 2>&1; then
	node_ver="$(node -p 'process.versions.node' 2>/dev/null || echo 0.0.0)"
	major="${node_ver%%.*}"
	rest="${node_ver#*.}"
	minor="${rest%%.*}"
	if ! { [ "$major" -gt 22 ] ||
		{ [ "$major" -eq 22 ] && [ "$minor" -ge 12 ]; } ||
		{ [ "$major" -eq 20 ] && [ "$minor" -ge 19 ]; }; }; then
		need "Node.js 22.12+ (or 20.19+); found $node_ver. Install the current LTS from
    https://nodejs.org/ or with a version manager (e.g. \`nvm install 22\`)."
	fi
else
	need "Node.js 22.12+ (or 20.19+): https://nodejs.org/ or a version manager (e.g. \`nvm install 22\`)."
fi
if ! command -v npm >/dev/null 2>&1; then
	need "npm (ships with Node.js; reinstall Node if it is missing)."
fi
if [ -n "$missing" ]; then
	printf 'Setup needs a few things first:'
	printf '%b\n' "$missing"
	echo
	echo "Install them, then run \`just setup\` again."
	echo "Prefer Docker? \`just up\` needs only Docker (or OrbStack) and just; see the README."
	exit 1
fi

# --- .env -------------------------------------------------------------------
# Before migrating: the app (and alembic) read AA_DATABASE_URL from .env.
if [ -f .env ]; then
	say ".env already exists; leaving it as is"
else
	cp .env.example .env
	say "created .env from .env.example"
fi

# --- Dependencies and schema ------------------------------------------------
say "installing Python dependencies (uv sync${extras:+ $extras})"
# shellcheck disable=SC2086
uv sync $extras

say "creating/upgrading the database schema (alembic upgrade head)"
uv run alembic upgrade head

say "installing frontend dependencies (npm ci)"
(cd frontend && npm ci)

# --- Next step --------------------------------------------------------------
say "setup complete"
if grep -Eq '^ANTHROPIC_API_KEY=(sk-ant-xxxxx)?[[:space:]]*$' .env; then
	echo "Next: set ANTHROPIC_API_KEY in .env (get a key at https://console.anthropic.com/),"
	echo "      then run \`just dev\` and open http://localhost:5173"
else
	echo "Next: run \`just dev\` and open http://localhost:5173"
fi
echo "Optional: \`just seed\` adds a starter topic to explore."
