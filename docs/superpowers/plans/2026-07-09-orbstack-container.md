# OrbStack Container Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run Adaptive Academy as a single always-on Docker container in OrbStack — FastAPI serving both the `/api/*` routes and the static-built SvelteKit frontend at `http://localhost:8000`, with the SQLite db in a named volume and the Obsidian vault bind-mounted.

**Architecture:** Multi-stage Dockerfile (node builds the frontend to static SPA files; python:3.12-slim + uv runs the backend and serves the build). `create_app()` gains a conditional SPA catch-all route. Compose defines the one service, the `adaptive-academy-data` volume, and the vault mount. A one-time justfile recipe snapshots the host db into the volume.

**Tech Stack:** FastAPI/uvicorn, SvelteKit 2 + `@sveltejs/adapter-static`, uv, Docker Compose (OrbStack), SQLite, Alembic.

**Spec:** `docs/superpowers/specs/2026-07-09-orbstack-container-design.md`

## Global Constraints

- Python `>=3.12`; dependencies managed by uv (`uv.lock` is authoritative — `uv sync --frozen` in the image).
- Container supports API-key LLM mode only: `ANTHROPIC_API_KEY` via env. Never bake `.env` or any key into the image.
- Database URL comes from `AA_DATABASE_URL` (pydantic-settings, prefix `AA_`); in the container it is `sqlite:////data/adaptive_academy.db`.
- Host dev workflow (`just api`, `just frontend`) must keep working unchanged; the SPA route mounts only when the build directory exists.
- All API routes live under `/api/...`; the SPA catch-all must never shadow them and must return 404 (not index.html) for unknown `/api/...` paths.
- Out of scope: dev-mode compose profile, nginx, `agent_sdk` in container, multi-arch publishing.

---

### Task 1: SPA static serving in FastAPI

**Files:**
- Modify: `src/adaptive_academy/settings.py` (add `frontend_dist` field)
- Modify: `src/adaptive_academy/api/app.py` (add `_mount_spa`, call it at end of `create_app()`)
- Test: `tests/test_spa_static.py` (new)

**Interfaces:**
- Consumes: `settings` singleton from `adaptive_academy.settings` (env prefix `AA_`).
- Produces: `Settings.frontend_dist: str = "frontend/build"` (env `AA_FRONTEND_DIST`); `create_app()` serves files from that directory at `/` with `index.html` fallback when the directory exists. Task 3's Dockerfile sets `AA_FRONTEND_DIST=/app/frontend/build`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_spa_static.py`:

```python
from fastapi.testclient import TestClient

from adaptive_academy.api.app import create_app
from adaptive_academy.settings import settings


def _spa_client(tmp_path, monkeypatch) -> TestClient:
    (tmp_path / "index.html").write_text("<html>SPA SHELL</html>")
    assets = tmp_path / "_app"
    assets.mkdir()
    (assets / "bundle.js").write_text("console.log('hi')")
    monkeypatch.setattr(settings, "frontend_dist", str(tmp_path))
    return TestClient(create_app())


def test_root_serves_index(tmp_path, monkeypatch):
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "SPA SHELL" in resp.text


def test_deep_client_route_falls_back_to_index(tmp_path, monkeypatch):
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/topics/3/tutor")
    assert resp.status_code == 200
    assert "SPA SHELL" in resp.text


def test_real_asset_served_directly(tmp_path, monkeypatch):
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/_app/bundle.js")
    assert resp.status_code == 200
    assert "console.log" in resp.text


def test_api_routes_still_win(tmp_path, monkeypatch):
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/api/health")
    assert resp.json() == {"status": "ok"}


def test_unknown_api_path_is_404_not_index(tmp_path, monkeypatch):
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/api/nope")
    assert resp.status_code == 404


def test_path_traversal_does_not_escape_dist(tmp_path, monkeypatch):
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("s3cret")
    client = _spa_client(tmp_path, monkeypatch)
    resp = client.get("/../secret.txt")
    assert "s3cret" not in resp.text


def test_no_dist_dir_means_no_spa_route(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "frontend_dist", str(tmp_path / "missing"))
    client = TestClient(create_app())
    resp = client.get("/")
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_spa_static.py -v`
Expected: FAIL — `AttributeError: 'Settings' object has no attribute 'frontend_dist'` (monkeypatch.setattr on a missing attribute raises), and the no-dist test may pass trivially. Failures are the point.

- [ ] **Step 3: Implement settings field and SPA mount**

In `src/adaptive_academy/settings.py`, add one field to `Settings`:

```python
    # Static frontend build to serve at / (env AA_FRONTEND_DIST). The Docker image
    # points this at the baked-in SvelteKit build; absent in host dev, so no-op there.
    frontend_dist: str = "frontend/build"
```

In `src/adaptive_academy/api/app.py`, add imports at the top:

```python
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from adaptive_academy.settings import settings
```

(Keep the existing imports; only `HTTPException`, `FileResponse`, `Path`, and `settings` are new.)

Add this function at module level (after `drop_api_key_if_agent_sdk`):

```python
def _mount_spa(app: FastAPI) -> None:
    """Serve the built SvelteKit SPA when a build directory exists (i.e. in the
    container image). Registered last so every /api route wins; unknown /api paths
    stay 404 rather than returning index.html to a confused API client."""
    dist = Path(settings.frontend_dist).resolve()
    index = dist / "index.html"
    if not index.is_file():
        return

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_relative_to(dist) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)
```

At the end of `create_app()`, immediately before `return app`:

```python
    _mount_spa(app)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_spa_static.py -v`
Expected: all 7 PASS.

- [ ] **Step 5: Run the full suite to check for regressions**

Run: `uv run pytest -q`
Expected: everything passes (the SPA route only mounts when `frontend/build/index.html` exists, which it doesn't in the repo checkout — and `frontend/build/` is gitignored).

- [ ] **Step 6: Commit**

```bash
git add src/adaptive_academy/settings.py src/adaptive_academy/api/app.py tests/test_spa_static.py
git commit -m "feat(api): serve static frontend build with SPA fallback when present"
```

---

### Task 2: Frontend static-SPA build

**Files:**
- Create: `frontend/svelte.config.js`
- Create: `frontend/src/routes/+layout.ts`
- Modify: `frontend/package.json` + `frontend/package-lock.json` (via `npm install`)

**Interfaces:**
- Produces: `npm run build` in `frontend/` emits a pure-SPA build at `frontend/build/` with `index.html` as fallback shell plus `_app/` assets. Task 3's Dockerfile runs this build and copies `build/` into the image.

Context: the project currently has **no** `svelte.config.js` (dev runs on vite-plugin-svelte defaults, and `npm run build` has never been exercised). There are no SvelteKit server routes; `/api` is proxied by Vite in dev only. Routes include dynamic ones (`/topics/[id]/...`), so the build must use adapter-static's SPA fallback rather than prerendering.

- [ ] **Step 1: Install adapter-static**

```bash
cd frontend && npm install -D @sveltejs/adapter-static
```

Expected: package.json devDependencies gains `@sveltejs/adapter-static`; lockfile updates. (`@sveltejs/adapter-auto` may remain; it's unused once a config names the adapter.)

- [ ] **Step 2: Create the SvelteKit config**

Create `frontend/svelte.config.js`:

```js
import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
export default {
  kit: {
    // Pure SPA: no prerendering, one index.html fallback for all client routes.
    // FastAPI serves this build in the container (see Dockerfile).
    adapter: adapter({ fallback: 'index.html' })
  }
};
```

- [ ] **Step 3: Disable SSR/prerender at the root**

Create `frontend/src/routes/+layout.ts`:

```ts
// SPA mode: the app talks to the FastAPI backend at runtime; nothing is
// prerendered at build time and there is no node server in production.
export const ssr = false;
export const prerender = false;
```

- [ ] **Step 4: Build and verify the output**

```bash
cd frontend && npm run build && ls build/ && test -f build/index.html && echo BUILD_OK
```

Expected: build succeeds, `BUILD_OK` printed, `build/` contains `index.html` and `_app/`. If the build errors mentioning prerendering or a missing fallback, the config from Steps 2-3 wasn't picked up — re-check file locations.

- [ ] **Step 5: Verify host dev still works**

```bash
cd frontend && npm run check
```

Expected: `svelte-check` completes with the same error/warning count as before this task (run it on `main` first if unsure; the config addition must not introduce new errors). Optionally confirm `npm run dev` still boots.

- [ ] **Step 6: Commit**

```bash
git add frontend/svelte.config.js frontend/src/routes/+layout.ts frontend/package.json frontend/package-lock.json
git commit -m "feat(frontend): static SPA build via adapter-static for container serving"
```

---

### Task 3: Dockerfile, entrypoint, .dockerignore

**Files:**
- Create: `Dockerfile`
- Create: `docker/entrypoint.sh`
- Create: `.dockerignore`

**Interfaces:**
- Consumes: `frontend/` static build tooling (Task 2), `AA_FRONTEND_DIST` setting (Task 1), `alembic upgrade head` (existing migrations in `alembic/versions/`, wired to `AA_DATABASE_URL` via `alembic/env.py` → `adaptive_academy.db.engine`).
- Produces: image `adaptive-academy` exposing port 8000, entrypoint that migrates then serves. Task 4's compose builds this.

- [ ] **Step 1: Create `.dockerignore`**

```
.git
.venv
.env
.env_template
.ruff_cache
.superpowers
.claude
__pycache__
**/__pycache__
*.db
*.db-wal
*.db-shm
*.db.bak-*
frontend/node_modules
frontend/.svelte-kit
frontend/build
docs
tests
```

(`frontend/build` is excluded because the image builds the frontend itself in stage 1 — a stale host build must never leak into the context.)

- [ ] **Step 2: Create `docker/entrypoint.sh`**

```sh
#!/bin/sh
# Migrate, then serve. `set -e` makes a failed migration stop the container
# visibly in OrbStack instead of serving against a half-migrated schema.
set -e

alembic upgrade head
exec uvicorn adaptive_academy.api.app:app --host 0.0.0.0 --port 8000
```

Then: `chmod +x docker/entrypoint.sh`

- [ ] **Step 3: Create `Dockerfile`**

```dockerfile
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
```

- [ ] **Step 4: Build the image**

```bash
docker build -t adaptive-academy:dev .
```

Expected: both stages succeed. Common failures: `npm ci` needs the Task 2 lockfile committed; `uv sync --frozen` fails if `uv.lock` is out of date (run `uv lock` on host if so).

- [ ] **Step 5: Smoke-test the container against a throwaway volume**

```bash
docker run -d --name aa-smoke -p 8001:8000 -v aa-smoke-data:/data adaptive-academy:dev
sleep 3
curl -sf http://localhost:8001/api/health          # → {"status":"ok"}
curl -sf http://localhost:8001/ | head -c 200      # → SvelteKit index.html
curl -sf http://localhost:8001/fleet | head -c 200 # → same index.html (SPA fallback)
curl -s -o /dev/null -w '%{http_code}' http://localhost:8001/api/nope  # → 404
docker logs aa-smoke | head -20                    # alembic ran, uvicorn started
docker rm -f aa-smoke && docker volume rm aa-smoke-data
```

Expected: health JSON, HTML shell for both `/` and `/fleet`, 404 for the bad API path, alembic migration lines in the log. (No `ANTHROPIC_API_KEY` yet — LLM routes would 502, that's fine here.)

- [ ] **Step 6: Commit**

```bash
git add Dockerfile docker/entrypoint.sh .dockerignore
git commit -m "feat(docker): multi-stage image — static frontend + uv-managed FastAPI"
```

---

### Task 4: Compose file, env plumbing, justfile targets

**Files:**
- Create: `compose.yaml`
- Modify: `.env.example` (document new vars)
- Modify: `.env` (add `OBSIDIAN_VAULT_PATH`)
- Modify: `justfile` (add `up`, `down`, `logs`)

**Interfaces:**
- Consumes: image build from Task 3.
- Produces: service `app`, named volume `adaptive-academy-data` mounted at `/data` (Task 5 copies the db into this exact volume name), vault at `/vault`.

- [ ] **Step 1: Create `compose.yaml`**

```yaml
services:
  app:
    build: .
    ports:
      - "8000:8000"
    restart: unless-stopped
    environment:
      AA_DATABASE_URL: sqlite:////data/adaptive_academy.db
      AA_OBSIDIAN_VAULT_PATH: /vault
      ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
      DEFAULT_MODEL: ${DEFAULT_MODEL:-}
    volumes:
      - aa-data:/data
      # iCloud-synced vault: files evicted by iCloud may read as empty in the
      # container until macOS re-materializes them.
      - "${OBSIDIAN_VAULT_PATH}:/vault"

volumes:
  aa-data:
    name: adaptive-academy-data
```

- [ ] **Step 2: Add vault path to env files**

Append to `.env` (real value):

```
OBSIDIAN_VAULT_PATH=/Users/you/Library/Mobile Documents/iCloud~md~obsidian/Documents/HomeVault
```

Update `.env.example` to:

```
ANTHROPIC_API_KEY=sk-ant-xxxxx
AA_DATABASE_URL=sqlite:///./adaptive_academy.db
# Host path bind-mounted to /vault in the container (docker compose only)
OBSIDIAN_VAULT_PATH=/absolute/path/to/your/obsidian/vault
```

- [ ] **Step 3: Add justfile targets**

Append to `justfile`:

```just
up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f
```

(justfile uses tabs for recipe bodies — match the existing recipes.)

- [ ] **Step 4: Validate compose config**

```bash
docker compose config
```

Expected: rendered config with the vault path expanded from `.env`, volume named `adaptive-academy-data`, `ANTHROPIC_API_KEY` populated. **Do not `just up` yet** — first boot would create a fresh db in the volume and Task 5's migration would then (correctly) refuse to overwrite it.

- [ ] **Step 5: Commit**

```bash
git add compose.yaml .env.example justfile
git commit -m "feat(docker): compose service with data volume and Obsidian vault mount"
```

(`.env` is gitignored — verify with `git status` that it isn't staged.)

---

### Task 5: One-time db migration into the volume, then first boot

**Files:**
- Modify: `justfile` (add `db-migrate-to-volume`)

**Interfaces:**
- Consumes: volume name `adaptive-academy-data` (Task 4), host `adaptive_academy.db` (live, WAL-mode).
- Produces: `/data/adaptive_academy.db` inside the volume; the running service at `http://localhost:8000`.

- [ ] **Step 1: Add the migration recipe**

Append to `justfile`:

```just
# One-time: snapshot the host sqlite db into the container volume.
# Refuses if the volume already holds a db; `just db-migrate-to-volume force=1` overrides.
db-migrate-to-volume force="":
	#!/usr/bin/env sh
	set -e
	snapdir="$(mktemp -d)"
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
	rm -rf "$snapdir"
```

(The `#!/usr/bin/env sh` shebang line makes just run the whole recipe as one script — needed for the temp-dir variable. `sqlite3 .backup` is WAL-safe, so the host app may even be running.)

- [ ] **Step 2: Run the migration**

```bash
just db-migrate-to-volume
```

Expected: `copied NNNNN bytes into volume` where NNNNN ≈ the host db size (~900KB once WAL content is folded in — the `.backup` includes uncheckpointed WAL pages; it should NOT be 0).

- [ ] **Step 3: Verify refusal guard**

```bash
just db-migrate-to-volume
```

Expected: exits non-zero with `refusing: /data/adaptive_academy.db already exists (use force=1)`.

- [ ] **Step 4: First boot with real data**

```bash
just up
sleep 3
curl -sf http://localhost:8000/api/health
curl -sf http://localhost:8000/api/topics | head -c 400
```

Expected: health ok; `/api/topics` returns your real topics (non-empty JSON matching what `curl localhost:8000/api/topics` showed in host dev), proving the container reads the migrated volume db and alembic upgraded it in place.

- [ ] **Step 5: Commit**

```bash
git add justfile
git commit -m "feat(docker): one-time host-db migration into the data volume"
```

---

### Task 6: End-to-end verification and README

**Files:**
- Modify: `README.md` (add "Run in a container" section)

**Interfaces:**
- Consumes: running compose service (Task 5).

- [ ] **Step 1: Verify the frontend end-to-end**

```bash
curl -sf http://localhost:8000/ | grep -o '<title>[^<]*' || curl -sf http://localhost:8000/ | head -c 300
curl -sf http://localhost:8000/fleet | head -c 300
```

Expected: both return the SvelteKit HTML shell. Then open `http://localhost:8000` in a browser and confirm the dashboard renders with real data (topics, fleet). OrbStack also serves it at the container's `*.orb.local` domain.

- [ ] **Step 2: Exercise one LLM-backed route**

Open the app in the browser and run one cheap LLM interaction (e.g. a Decay Check or one tutor message), OR from the shell confirm the key is present and let the user do the browser check:

```bash
docker compose exec app printenv ANTHROPIC_API_KEY | cut -c1-10
```

Expected: `sk-ant-...` prefix printed; the browser interaction returns a normal LLM response (not a 502 "check ANTHROPIC_API_KEY" error).

- [ ] **Step 3: Verify vault mount**

```bash
docker compose exec app ls /vault | head -5
```

Expected: your HomeVault's top-level notes/folders. (If files read as empty later, suspect iCloud eviction — documented in the spec.)

- [ ] **Step 4: Verify restart policy / management story**

```bash
docker compose restart app && sleep 3 && curl -sf http://localhost:8000/api/health
```

Expected: health ok after restart; container visible and start/stoppable in the OrbStack UI.

- [ ] **Step 5: Add README section**

Append to `README.md` (adjust placement to fit the existing structure — after the dev setup section):

```markdown
## Run in a container (Docker / OrbStack)

Build and run the whole app (API + built frontend) as one service on
http://localhost:8000, with the SQLite db in a named volume:

​```bash
cp .env.example .env       # set ANTHROPIC_API_KEY and OBSIDIAN_VAULT_PATH
just db-migrate-to-volume  # optional: copy an existing local db into the volume
just up                    # build image + start (docker compose up -d --build)
just logs                  # follow logs
just down                  # stop
​```

Notes:
- The container uses API-key mode only (`ANTHROPIC_API_KEY`); the `agent_sdk`
  subscription backend is host-only.
- Data lives in the `adaptive-academy-data` volume; the repo's
  `adaptive_academy.db` is untouched after migration. Avoid running host
  and container against the same db file.
- The Obsidian vault is bind-mounted read-write at `/vault`
  (`AA_OBSIDIAN_VAULT_PATH=/vault`).
```

(Remove the zero-width characters around the inner code fences — they're only here to nest the fences in this plan.)

- [ ] **Step 6: Run the full host test suite one last time**

```bash
uv run pytest -q
```

Expected: all pass.

- [ ] **Step 7: Commit**

```bash
git add README.md
git commit -m "docs: container quickstart (OrbStack/Docker)"
```
