# Adaptive Academy

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)

An **open-source, local-first, generation-first** AI learning tool for serious self-directed
adult learners — grounded in learning science, with an **observable multi-agent** spine instead
of one opaque chatbot.

It exists to **help people learn deeply** by building and shipping, and to do it in the open. Your
data stays on your machine; you bring your own Anthropic key. It's a personal, dogfooded project —
built to learn from, and shared so others can too.

The signature behaviour: the Tutor **withholds full solutions until you've logged an attempt** —
enforced in code (a gated `reveal_solution` tool), not just in the prompt. That "generation-first"
stance runs through the whole system.

## What it does

- **An orchestrated agent crew** you can watch work: a Researcher (fan-out source gathering), a
  CurriculumDirector (phased trackers toward a "North Star"), a Tutor, and an Assessor — coordinated
  through shared state, with an observability trace of "what the agents did."
- **Long-horizon Programs with verified-depth gates:** above single topics, a **Program** is a
  researched milestone map (e.g. "PhD-level prep in custom LLMs") that spawns topics on demand and
  gates progress on *evidence* — a milestone only "passes" when its load-bearing concepts survive a
  delayed, unassisted recall **and** a graded artifact. The map **re-researches itself** against what
  you've learned and what's changed in the field, proposing a reviewable diff you accept or reject.
- **Anti-Goodhart competence triangulation:** a concept is "solid" only when multiple independent
  signals agree (graded self-explanation, decay/recall, calibration, teach-back, shipped artifacts)
  — never a single grade.
- **Deliberate practice under pressure:** spar with an auto-generated **persona** (a skeptical
  buyer, a staff engineer in a design review, a thesis committee) or get **probed on a real paper**
  (an arXiv link or pasted text) with a structured, generation-first critical-reading examiner —
  both blind-graded per concept into the same milestone gates, so *defending* your understanding is
  how you prove it.
- **The Voyage:** a forgiving, game-like momentum layer (per-topic "wind" + a cross-topic **Fleet**)
  that models whether you *keep going*, derived from your real activity and kept independent of
  competence.
- **Local-first interop:** ingest your Obsidian vault notes as grounding sources, and export your
  concepts/track back out as linked markdown.
- **Memory & retrieval:** everything you read, write, and get told is indexed locally —
  vault notes (full text, with `[[wikilinks]]`), accepted sources, probed papers, your own
  answers, the Tutor's explanations, and every generated question — in SQLite (FTS5, plus
  optional `sqlite-vec` hybrid ranking with an in-process embedder). The Tutor grounds on it
  and sees what it already explained ("What it remembered"); practice generators reject
  near-duplicate questions in code.
- **A traversable concept graph + Scout:** prerequisite edges are materialized (bi-temporal,
  never deleted) and walked with recursive CTEs — remediation targets the weakest ancestor,
  the map shows real edges — and a Scout proposes new topics from evidence (frontier concepts,
  orphan terms in your own writing, unlinked vault notes, paper "extend" answers) as
  reviewable suggestions you accept or dismiss.

## Honest note on cost & privacy

This is **BYOK** — it runs on *your* Anthropic API key. It's a **multi-agent** system, so a rich
session (research → curriculum → assess → tutor) consumes **real tokens** and can cost a few dollars.
That's the trade for depth and for keeping your data local. Note too that while your data is stored
locally, the substance of each AI call is still sent to Anthropic's API — "local-first" here means
your *records* live on your machine, not that inference is offline.

**See what it costs.** Every model call is recorded locally (tokens, web searches, and the cost at
Anthropic's list prices). The **Usage** page (`/usage`, or `GET /api/usage`) shows spend for today,
the last 7 and 30 days, and all time, broken down by feature and by model. Models without a known
price still have their tokens recorded and show "price unknown". In `agent_sdk` mode the dollar
figure is the Agent SDK's own estimate; your Claude subscription pays, not an API key.

**Cap it.** Set `AA_DAILY_BUDGET_USD=5` (any dollar amount, `0` to block every API-key call) in
`.env` and restart the API. Before each API-key model call the app checks today's recorded spend;
once it meets the limit, new calls are refused with a 429 that says what was spent and how to raise
the limit. "Today" is the server's local day (UTC in the Docker image unless you set `TZ`). It is a
soft cap on *recorded* spend at list price, not a hard billing limit:

- The check runs before a call and a call's cost is only known after it, so the call that crosses
  the limit (and any research searches already in flight alongside it) can overshoot it. Searches
  not yet started are cancelled.
- The SDK's own automatic retries (after a timeout or a dropped connection) aren't reported back,
  so the rare retried call is undercounted.
- A model with no known price can't be capped, so while a limit is set, calls on such a model
  (e.g. `AA_MODEL_REASONING=` a model not in the price table) are refused with a 429 that names it,
  and `GET /api/setup` and the Usage page warn about it. Use a priced model or unset the limit.

Agent SDK (subscription) calls are recorded but never blocked. For a hard ceiling, also set a
spend limit on the key in the Anthropic Console.

## Stack

Python 3.12 · FastAPI · SQLModel · SQLite (WAL) · Alembic · Anthropic SDK ·
SvelteKit 2 / Svelte 5 / Tailwind 4. Package manager: `uv`. Task runner: `just`.

## Quickstart (Docker)

The shortest path: the whole app (API + built frontend) as one container on
http://localhost:8000, with the SQLite db in a named volume. You need
[Docker](https://docs.docker.com/get-docker/) or [OrbStack](https://orbstack.dev/), and
[`just`](https://github.com/casey/just).

```bash
cp .env.example .env   # then edit .env and set ANTHROPIC_API_KEY=sk-ant-...
just up                # build the image and start it (docker compose up -d --build)
```

Open http://localhost:8000. No `just`? Run `mkdir -p data/vault && docker compose up -d --build`
instead (`docker compose logs -f` and `docker compose down` for the other two below).

```bash
just logs                  # follow logs
just down                  # stop
just db-migrate-to-volume  # optional: copy an existing local db into the volume
```

`OBSIDIAN_VAULT_PATH` in `.env` is optional (see the vault note below).

Notes:
- The container uses API-key mode only (`ANTHROPIC_API_KEY`); the `agent_sdk`
  subscription backend is host-only.
- Data lives in the `adaptive-academy-data` volume; the repo's
  `adaptive_academy.db` is untouched after migration. Avoid running host
  and container against the same db file.
- The app runs as an unprivileged user, uid/gid 1000 by default (`AA_UID` / `AA_GID` in
  `.env`), not as root. On start the container hands `/data` to that user; volumes from
  earlier versions, which ran as root, are root-owned, and the first start fixes them. It
  never changes ownership of anything in your vault.
- On Linux, set `AA_UID=$(id -u)` and `AA_GID=$(id -g)` in `.env` so the notes the app
  exports into your vault are owned by you. `.env` doesn't run commands, so write the numbers:
  `echo "AA_UID=$(id -u)" >> .env && echo "AA_GID=$(id -g)" >> .env`. On macOS, Docker
  Desktop and OrbStack give bind-mounted files your own user whatever the uid, so the default
  is fine. If the vault isn't writable by that uid, the app still starts (the log says so) and
  a vault export fails with a message saying what to set.
- The Obsidian vault is bind-mounted read-write at `/vault`
  (`AA_OBSIDIAN_VAULT_PATH=/vault`). With `OBSIDIAN_VAULT_PATH` unset, the
  mount is the gitignored `./data/vault`, and vault exports land there. `just up`
  creates that folder first; if you run `docker compose up` directly on Linux,
  run `mkdir -p data/vault` before it, or Docker creates the folder as root.
- Quote `OBSIDIAN_VAULT_PATH` in `.env` if the path contains spaces (e.g.
  `OBSIDIAN_VAULT_PATH="/Users/you/Library/Mobile Documents/..."`) —
  unquoted values with spaces break `just`'s dotenv parsing.

## Quickstart (local)

For working on the code. You need [`uv`](https://docs.astral.sh/uv/) (it fetches Python 3.12
itself), Node.js 22.12+ (or 20.19+) with npm, and [`just`](https://github.com/casey/just).

```bash
just setup   # once: checks prerequisites, installs deps, creates the db schema and .env
             # then edit .env and set ANTHROPIC_API_KEY=sk-ant-...
just dev     # API on :8000 + frontend on :5173 in one terminal; Ctrl-C stops both
```

Open http://localhost:5173. Start from the dashboard, generate a curriculum for a topic, then work
the daily loop (warm up → build → probe → teach back). The header surfaces the adaptive levers
(assistance / challenge) and "What the agents did" expands the observability trace.

Models default to `claude-sonnet-5-5` / `claude-haiku-5-5` (in Docker too). If one is retired or
not available to your key, set `AA_MODEL_REASONING` / `AA_MODEL_COPY` in `.env` and restart the API.

`just setup` is safe to re-run and never overwrites an existing `.env`. By hand, it amounts to:

```bash
cp .env.example .env          # only if .env doesn't exist yet
just install                  # uv sync (installs Python deps)
uv run alembic upgrade head   # create the SQLite schema
cd frontend && npm ci && cd ..
```

Optional extras:

```bash
just seed               # add the demo topic (a few weeks of example use; removable)
just setup --memory     # or `uv sync --extra memory`: sqlite-vec + fastembed for hybrid (BM25 + vector) retrieval
```

`just dev` prefixes each server's output with `[api]` / `[web]`, and if either server exits it
stops the other. Set `AA_API_PORT` / `AA_WEB_PORT` to move it off 8000 / 5173 (e.g.
`AA_API_PORT=8001 just dev` while the container holds 8000); the frontend's `/api` proxy
follows. Prefer two terminals? `just api` (FastAPI on http://localhost:8000) and
`just frontend` (SvelteKit on http://localhost:5173, proxies `/api` → :8000) still work.

> **Hybrid retrieval** needs the `memory` extra. The `bge-small` embedding model (~130 MB)
> downloads once into `AA_EMBEDDING_CACHE_DIR` (the container keeps it on the data volume).
> Without the extra, retrieval is FTS5/BM25 only — everything still works.
> Set `AA_EMBEDDING_ALLOW_DOWNLOAD=false` on strict offline hosts to require a cached model.
> A plain `just setup` (or `uv sync`) removes the extra again; re-run with `--memory`.

> **`just seed` is optional** — it adds the demo topic (the same one as "Explore a demo
> topic" on the empty home page), so there's something to explore without an API key. Remove
> it from its dashboard when you're done. The real entry point is creating your own
> **Program** (a researched milestone map) or topic from the app.

> **Tip:** start the API via `just dev` or `just api` (both load `.env`). Running
> `uv run uvicorn …` directly skips `.env`, so `ANTHROPIC_API_KEY` is missing and any
> model-backed call returns a 500.

> **Stale SPA:** running `cd frontend && npm run build` leaves a
> `frontend/build/` directory on the host (the Docker image builds its own copy inside the
> image and never writes one); host-dev `just api` will then
> serve that increasingly stale SPA at http://localhost:8000/ instead of
> a 404/API-only response. Run `rm -rf frontend/build` to restore pure-API
> host dev (frontend dev via `npm run dev` stays on :5173 either way).

## Test

```bash
just test                       # backend (pytest)
cd frontend && npx vitest run   # frontend (vitest)
cd frontend && npm run check    # frontend types (svelte-check)
```

End-to-end tests (Playwright) drive the real UI at desktop and phone sizes:

```bash
cd frontend
npx playwright install chromium   # once
npm run test:e2e
```

The e2e run starts its own API (via `uv`) on a fresh, seeded SQLite db with no
`ANTHROPIC_API_KEY`, plus a Vite server on its own ports (18765 and 14173; override with
`E2E_API_PORT` / `E2E_WEB_PORT`). It never touches your db, your vault, or your dev
servers, and no test spends tokens. CI (`.github/workflows/ci.yml`) runs all four suites.

## Back up and restore your data

Your whole learning record (topics, concepts, assessments, gates, conversations, the agent
trace) is one SQLite file: `adaptive_academy.db` in the repo for host dev, or
`/data/adaptive_academy.db` inside the `adaptive-academy-data` Docker volume.

**Back up.** Each of these is safe while the app is running:

```bash
just backup          # snapshot -> backups/adaptive_academy-YYYYMMDD-HHMMSS.db
just export          # full record as JSON -> backups/adaptive_academy-YYYYMMDD-HHMMSS.json
uv run aa backup ~/somewhere/   # or name a directory / file yourself
```

The `.db` snapshot is a consistent copy made with SQLite's online backup API: one
self-contained file you can restore. The `.json` export (`"format": "adaptive-academy-export"`,
`"version": 1`) holds every table's rows for reading or migrating elsewhere; it leaves out the
search indexes (`chunk_fts`, `chunk_vec`), which the app rebuilds. `backups/` is gitignored.

In the container (or from any browser), open **Your data** in the sidebar and download either
file, or fetch them directly:

```bash
curl -OJ http://localhost:8000/api/export/backup   # .db snapshot
curl -OJ http://localhost:8000/api/export/record   # .json export
```

**Restore** a `.db` snapshot (the JSON export is for reading, not restoring). Stop the app
first. On the host:

```bash
uv run aa restore backups/adaptive_academy-YYYYMMDD-HHMMSS.db --force
uv run alembic upgrade head     # bring an older snapshot up to the current schema
```

`aa restore` refuses to replace an existing db without `--force`, and saves the current one to
`backups/adaptive_academy-pre-restore-*.db` first. To restore by hand instead, stop the app,
delete `adaptive_academy.db-wal` and `adaptive_academy.db-shm` if present (a stale WAL would be
replayed onto the restored file), copy the snapshot to `adaptive_academy.db`, and run
`uv run alembic upgrade head`.

For Docker, download a backup of the current data first, then copy the snapshot into the
volume (the same way `just db-migrate-to-volume` does); the container runs
`alembic upgrade head` on start:

```bash
just down
docker run --rm -v adaptive-academy-data:/data -v "$PWD/backups":/host alpine sh -c '
  rm -f /data/adaptive_academy.db-wal /data/adaptive_academy.db-shm &&
  cp /host/adaptive_academy-YYYYMMDD-HHMMSS.db /data/adaptive_academy.db'
just up
```

## Design & evidence

This project is **built in public, spec-first**: each capability starts as a written design spec,
becomes a bite-sized implementation plan, then ships via subagent-driven development with adversarial
code review. Those documents *are* the build log — a fuller record of the reasoning than the code
alone, and the most interesting part to read if you're here to learn from the process.

- Overview (architecture + goal): [`docs/OVERVIEW.md`](docs/OVERVIEW.md)
- Learning-science evidence base (cited, adversarially verified): [`docs/research/`](docs/research/)
- Design specs, per capability: [`docs/superpowers/specs/`](docs/superpowers/specs/) — e.g. the
  [original redesign](docs/superpowers/specs/2026-06-15-adaptive-academy-redesign.md), the
  [Program layer](docs/superpowers/specs/2026-07-09-program-layer.md),
  [Map Revision](docs/superpowers/specs/2026-07-10-map-revision.md),
  [Roleplay / Examiner](docs/superpowers/specs/2026-07-15-roleplay-examiner-design.md), and
  [Paper Probe](docs/superpowers/specs/2026-07-15-paper-probe-design.md)
- Implementation plans (TDD, task-by-task): [`docs/superpowers/plans/`](docs/superpowers/plans/)

## Status & contributing

Pre-1.0 and actively built in public — expect rough edges and moving parts. Issues, ideas, and PRs
that help people learn are welcome — see [`CONTRIBUTING.md`](CONTRIBUTING.md), the
[Code of Conduct](CODE_OF_CONDUCT.md), and the [security policy](SECURITY.md). (A smoother
first-run / PWA path is still on the near-term list.)

## License

[Apache 2.0](LICENSE) © 2026 Thomas Sullivan
