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

## Stack

Python 3.12 · FastAPI · SQLModel · SQLite (WAL) · Alembic · Anthropic SDK ·
SvelteKit 2 / Svelte 5 / Tailwind 4. Package manager: `uv`. Task runner: `just`.

## Prerequisites

- [`uv`](https://docs.astral.sh/uv/) (Python)
- Node.js (for the SvelteKit frontend)
- An `ANTHROPIC_API_KEY` — copy `.env.example` to `.env` and set it:

  ```bash
  cp .env.example .env
  # then edit .env and set ANTHROPIC_API_KEY=sk-ant-...
  ```

## Setup (run once)

```bash
just install                  # uv sync (installs Python deps)
uv run alembic upgrade head   # create the SQLite schema
just seed                     # optional: drop in a starter "Build LLMs from scratch" topic
cd frontend && npm install && cd ..
uv sync --extra memory        # optional: sqlite-vec + fastembed for hybrid (BM25 + vector) retrieval
```

> **Hybrid retrieval** needs the `memory` extra. The `bge-small` embedding model (~130 MB)
> downloads once into `AA_EMBEDDING_CACHE_DIR` (the container keeps it on the data volume).
> Without the extra, retrieval is FTS5/BM25 only — everything still works.
> Set `AA_EMBEDDING_ALLOW_DOWNLOAD=false` on strict offline hosts to require a cached model.

> Hybrid memory needs `uv sync --extra memory`. Compose caches the model at
> `/data/fastembed_cache`. The download happens once per `aa-data` volume.

> **`just seed` is optional** — it seeds one starter topic so there's something to explore
> immediately. Otherwise you start from an empty state and create your own **Program** (a
> researched milestone map) or topic from the app — that's the real entry point.

## Run

Two terminals:

```bash
just api        # FastAPI on http://localhost:8000
just frontend   # SvelteKit on http://localhost:5173  (proxies /api → :8000)
```

Open http://localhost:5173. Start from the dashboard, generate a curriculum for a topic, then work
the daily loop (warm up → build → probe → teach back). The header surfaces the adaptive levers
(assistance / challenge) and "What the agents did" expands the observability trace.

> **Tip:** start the API via `just api` (it loads `.env`). Running `uv run uvicorn …` directly
> skips `.env`, so `ANTHROPIC_API_KEY` is missing and any model-backed call returns a 500.

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

## Run in a container (Docker / OrbStack)

Build and run the whole app (API + built frontend) as one service on
http://localhost:8000, with the SQLite db in a named volume:

```bash
cp .env.example .env       # set ANTHROPIC_API_KEY (OBSIDIAN_VAULT_PATH is optional)
just db-migrate-to-volume  # optional: copy an existing local db into the volume
just up                    # build image + start (docker compose up -d --build)
just logs                  # follow logs
just down                  # stop
```

Notes:
- The container uses API-key mode only (`ANTHROPIC_API_KEY`); the `agent_sdk`
  subscription backend is host-only.
- Data lives in the `adaptive-academy-data` volume; the repo's
  `adaptive_academy.db` is untouched after migration. Avoid running host
  and container against the same db file.
- The Obsidian vault is bind-mounted read-write at `/vault`
  (`AA_OBSIDIAN_VAULT_PATH=/vault`). With `OBSIDIAN_VAULT_PATH` unset, the
  mount is the gitignored `./data/vault`, and vault exports land there. `just up`
  creates that folder first; if you run `docker compose up` directly on Linux,
  run `mkdir -p data/vault` before it, or Docker creates the folder as root.
  The container itself runs as root, so on Linux the notes it exports into any
  vault are root-owned on the host; `sudo chown -R "$USER" <vault>` takes them back.
- Quote `OBSIDIAN_VAULT_PATH` in `.env` if the path contains spaces (e.g.
  `OBSIDIAN_VAULT_PATH="/Users/you/Library/Mobile Documents/..."`) —
  unquoted values with spaces break `just`'s dotenv parsing.
- Building the image (or running `cd frontend && npm run build`) leaves a
  `frontend/build/` directory on the host; host-dev `just api` will then
  serve that increasingly stale SPA at http://localhost:8000/ instead of
  a 404/API-only response. Run `rm -rf frontend/build` to restore pure-API
  host dev (frontend dev via `npm run dev` stays on :5173 either way).

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
