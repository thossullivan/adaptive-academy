set dotenv-load := true

install:
	uv sync

seed:
	uv run aa seed

api:
	uv run uvicorn adaptive_academy.api.app:app --reload --port 8000

frontend:
	cd frontend && npm run dev

test:
	uv run pytest -q

up:
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
