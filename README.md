# Adaptive Academy

A private, local-first, **generation-first** AI tutoring tool for advanced adult
self-directed learning. This is the **walking-skeleton** milestone: a runnable
end-to-end slice — a Tutor you can chat with about a seeded topic, proving the
plumbing + orchestration spine + initial UI.

The signature behaviour: the Tutor **withholds full solutions until you've logged an
attempt** — enforced in code (a gated `reveal_solution` tool), not just in the prompt.

- Design spec: [`docs/superpowers/specs/2026-06-15-adaptive-academy-redesign.md`](docs/superpowers/specs/2026-06-15-adaptive-academy-redesign.md)
- Evidence base (cited): [`docs/research/2026-06-15-learning-science-evidence.md`](docs/research/2026-06-15-learning-science-evidence.md)
- This plan: [`docs/superpowers/plans/2026-06-15-tutor-walking-skeleton.md`](docs/superpowers/plans/2026-06-15-tutor-walking-skeleton.md)

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
just install            # uv sync (installs Python deps)
uv run alembic upgrade head   # create the SQLite schema
just seed               # seed the "Build LLMs from scratch" topic  ← REQUIRED
cd frontend && npm install && cd ..
```

> **Don't skip `just seed`.** Without it the database has no topic, and the chat page
> loads to an empty state with nothing to talk about.

## Run

Two terminals:

```bash
just api        # FastAPI on http://localhost:8000
just frontend   # SvelteKit on http://localhost:5173  (proxies /api → :8000)
```

Open http://localhost:5173. Ask the tutor for the answer to a concept — it will give a
hint and ask you to attempt first. Once you make a genuine attempt, the **attempt:
logged** indicator flips and it will confirm/expand. The header shows the two adaptive
levers (assistance / challenge); "What the agents did" expands the observability trace.

## Test

```bash
just test                       # backend (pytest)
cd frontend && npx vitest run   # frontend (vitest)
```

## What's deferred (later milestones)

Researcher (fan-out source gathering), CurriculumDirector (phased trackers), Assessor
(rubric/anchor-graded self-explanation + curated spaced repetition), the build-in-public
log, streaming responses, and auth. See the spec for the full design.
