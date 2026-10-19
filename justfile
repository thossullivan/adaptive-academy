set dotenv-load := true

# One-time local setup (prereqs, deps, db schema, .env); --memory adds hybrid retrieval.
setup *args:
	./scripts/setup.sh {{args}}

install:
	uv sync

seed:
	uv run aa seed

graph-backfill:
	uv run aa graph-backfill

# Consistent snapshot of the local db -> backups/adaptive_academy-<timestamp>.db (or PATH)
backup *path:
	uv run aa backup {{path}}

# Full learning record as versioned JSON -> backups/adaptive_academy-<timestamp>.json (or PATH)
export *path:
	uv run aa export {{path}}

api:
	uv run uvicorn adaptive_academy.api.app:app --reload --port 8000

frontend:
	cd frontend && npm run dev

# API + frontend in one terminal; Ctrl-C stops both. Ports: AA_API_PORT / AA_WEB_PORT.
dev:
	./scripts/dev.sh

test:
	uv run pytest -q

# Create compose's default vault mount first: on Linux, Docker would create it as root.
up:
	mkdir -p data/vault
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f

# One-time: snapshot the host sqlite db into the container volume.
# Refuses if the volume already holds a db; `just db-migrate-to-volume force=1` overrides.
db-migrate-to-volume force="":
	#!/usr/bin/env sh
	set -e
	snapdir="$(mktemp -d)"
	trap 'rm -rf "$snapdir"' EXIT
	sqlite3 adaptive_academy.db ".backup '$snapdir/adaptive_academy.db'"
	docker volume create adaptive-academy-data >/dev/null
	docker run --rm -v adaptive-academy-data:/data -v "$snapdir":/host -e FORCE="{{force}}" alpine sh -c '
		if [ -f /data/adaptive_academy.db ] && [ "$FORCE" != "1" ]; then
			echo "refusing: /data/adaptive_academy.db already exists (use force=1)" >&2
			exit 1
		fi
		cp /host/adaptive_academy.db /data/adaptive_academy.db
		echo "copied $(wc -c < /data/adaptive_academy.db) bytes into volume"
	'
