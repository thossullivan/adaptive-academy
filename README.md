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
- **Anti-Goodhart competence triangulation:** a concept is "solid" only when multiple independent
  signals agree (graded self-explanation, decay/recall, calibration, teach-back, shipped artifacts)
  — never a single grade.
- **The Voyage:** a forgiving, game-like momentum layer (per-topic "wind" + a cross-topic **Fleet**)
  that models whether you *keep going*, derived from your real activity and kept independent of
  competence.
- **Local-first interop:** ingest your Obsidian vault notes as grounding sources, and export your
  concepts/track back out as linked markdown.

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
just seed                     # seed the "Build LLMs from scratch" topic  ← REQUIRED
cd frontend && npm install && cd ..
```

> **Don't skip `just seed`.** Without it the database has no topic and the app loads to an empty
> state with nothing to work on.

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
```

## Run in a container (Docker / OrbStack)

Build and run the whole app (API + built frontend) as one service on
http://localhost:8000, with the SQLite db in a named volume:

```bash
cp .env.example .env       # set ANTHROPIC_API_KEY and OBSIDIAN_VAULT_PATH
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
  (`AA_OBSIDIAN_VAULT_PATH=/vault`).
- Quote `OBSIDIAN_VAULT_PATH` in `.env` if the path contains spaces (e.g.
  `OBSIDIAN_VAULT_PATH="/Users/you/Library/Mobile Documents/..."`) —
  unquoted values with spaces break `just`'s dotenv parsing.
- Building the image (or running `cd frontend && npm run build`) leaves a
  `frontend/build/` directory on the host; host-dev `just api` will then
  serve that increasingly stale SPA at http://localhost:8000/ instead of
  a 404/API-only response. Run `rm -rf frontend/build` to restore pure-API
  host dev (frontend dev via `npm run dev` stays on :5173 either way).

## Design & evidence

- Overview (architecture + goal): [`docs/OVERVIEW.md`](docs/OVERVIEW.md)
- Design spec: [`docs/superpowers/specs/2026-06-15-adaptive-academy-redesign.md`](docs/superpowers/specs/2026-06-15-adaptive-academy-redesign.md)
- Learning-science evidence base (cited): [`docs/research/2026-06-15-learning-science-evidence.md`](docs/research/2026-06-15-learning-science-evidence.md)

## Status & contributing

Pre-1.0 and actively built in public — expect rough edges and moving parts. Issues, ideas, and PRs
that help people learn are welcome. (A `CONTRIBUTING.md` and a smoother first-run/PWA path are on the
near-term list.)

## License

[Apache 2.0](LICENSE) © 2026 Thomas Sullivan
