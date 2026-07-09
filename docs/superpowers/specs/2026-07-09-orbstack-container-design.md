# OrbStack Container Design

**Date:** 2026-07-09
**Status:** Approved

## Goal

Run Adaptive Academy as a single always-on container managed in OrbStack, serving the
whole app at `http://localhost:8000` (OrbStack also exposes an `*.orb.local` domain).
Development stays on the host exactly as today (`just api` / `just frontend`); the
container is a service, not a dev environment.

## Decisions

| Decision | Choice |
|---|---|
| Topology | Single container: FastAPI serves both `/api/*` and the built frontend |
| LLM backend | API-key mode only (`ANTHROPIC_API_KEY` via env). `AA_LLM_BACKEND=agent_sdk` remains host-only |
| Database | One-time migration of the existing `adaptive_academy.db` into a named Docker volume; host file becomes a frozen backup |
| Obsidian vault | Bind-mount `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/HomeVault` read-write at `/vault`, `AA_OBSIDIAN_VAULT_PATH=/vault` |

## Image: multi-stage Dockerfile

1. **Frontend stage** (`node:22-slim`): `npm ci && npm run build` producing a static
   SPA build. Requires swapping `@sveltejs/adapter-auto` for `@sveltejs/adapter-static`
   with SPA fallback (`fallback: 'index.html'`) in `frontend/svelte.config.js`. The app
   has no SvelteKit server routes (the dev Vite proxy handles `/api`), so this only
   changes build output; `npm run dev` on the host is unaffected.
2. **Runtime stage** (`python:3.12-slim`): install dependencies with
   `uv sync --no-dev` (uv copied from the official uv image), copy `src/`, `alembic/`,
   `alembic.ini`, and the frontend build output.
3. **Entrypoint script**: `alembic upgrade head`, then
   `uvicorn adaptive_academy.api.app:app --host 0.0.0.0 --port 8000` (no `--reload`).
   If migration fails, the script exits non-zero so the container stops visibly in
   OrbStack.

## Backend change: serve the static frontend

In `create_app()`, if a frontend build directory exists (settings field
`frontend_dist`, env `AA_FRONTEND_DIST`, default `frontend/build` — SvelteKit's
static-adapter output; the image sets it to the baked-in copy), mount it at `/`
with an SPA fallback so client-side routes like `/topics/3/tutor` return `index.html`.
All API routers already carry `/api/...` prefixes, so there is no route collision.
When the directory is absent (host dev, tests), behavior is unchanged.

## Compose (`compose.yaml`)

One service `app`:

- `build: .`, `ports: ["8000:8000"]`, `restart: unless-stopped`
- Named volume `aa-data` mounted at `/data`;
  `AA_DATABASE_URL=sqlite:////data/adaptive_academy.db`
- `ANTHROPIC_API_KEY` and `DEFAULT_MODEL` passed through from the repo `.env`
  (compose reads it automatically; the file is never baked into the image)
- Vault bind mount:
  `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/HomeVault:/vault` (rw),
  `AA_OBSIDIAN_VAULT_PATH=/vault`

**iCloud caveat:** the vault lives in iCloud Drive. Files evicted to the cloud
("dataless" placeholders) may read as empty from the container until macOS
materializes them. Acceptable for a local single-user setup; noted here so surprises
are diagnosable.

## One-time data migration

`just db-migrate-to-volume`:

1. On the host, snapshot the live database safely with
   `sqlite3 adaptive_academy.db ".backup '<tmp>/aa-snapshot.db'"` (WAL-safe).
2. Copy the snapshot into the `aa-data` volume via a throwaway container
   (`docker compose run --rm` or `docker run -v aa-data:/data`), placing it at
   `/data/adaptive_academy.db`.
3. Refuse to overwrite an existing db in the volume unless forced, to protect
   container-side history once the container becomes the writer.

The host repo db is left untouched as a frozen backup. Host and container must not
both serve writes long-term; after migration the container owns the data.

## Justfile additions

- `just up` — `docker compose up -d --build`
- `just down` — `docker compose down`
- `just logs` — `docker compose logs -f`
- `just db-migrate-to-volume` — as above

## Testing / verification

- Build the image; run the migration; `docker compose up`.
- `curl http://localhost:8000/api/topics` returns data from the migrated db.
- `curl http://localhost:8000/` returns the frontend `index.html`; a deep client
  route (e.g. `/fleet`) also returns `index.html` (SPA fallback).
- Exercise one LLM-backed route end-to-end to confirm the API key reaches the
  container.
- Existing pytest suite still passes on the host (backend change is
  conditional on the build directory existing).

## Out of scope (YAGNI)

- Dev-mode compose profile / hot reload in container
- nginx or any second service
- `agent_sdk` backend inside the container
- Multi-arch image publishing / registry push
