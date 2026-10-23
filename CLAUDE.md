# Adaptive Academy: Working Notes

Guidance for anyone (human or agent) working in this repo. For the product overview and the
architecture diagram, read [`docs/OVERVIEW.md`](docs/OVERVIEW.md); for setup and run instructions,
[`README.md`](README.md). This file captures the *how we build it* conventions.

## Core Philosophy

**Local-first, agent-orchestrated, generation-first learning.** A personal, private learning
environment where specialized agents coordinate through shared state, the competence model is kept
honest by triangulating independent signals, and the tutor withholds answers until you've generated
an attempt. The code enforces that rule; the prompt alone can't be trusted to.

## Stack

- **Backend:** Python 3.12 · FastAPI · SQLModel · SQLite (WAL) · Alembic · Anthropic SDK
- **Frontend:** SvelteKit 2 / Svelte 5 (runes) / Tailwind 4
- **Tooling:** `uv` (Python deps), `just` (task runner), `pytest` + `vitest` (tests), `ruff` +
  pre-commit. Runs locally or as a Docker/OrbStack compose service.

## Layout

```
src/adaptive_academy/
  models.py      SQLModel tables: the single source of truth
  prompts.py     version-tagged prompt registry (every tag traced into AgentEvent)
  db.py          engine/session, WAL + PRAGMA foreign_keys=ON
  api/           FastAPI routers (REST under /api)
  engine/        one module per capability: research, curriculum, tutor, assess,
                 decay, productive_failure, teach, momentum, gates, revision, vault, …
  llm/           pluggable client registry (Anthropic SDK / agent-SDK / scripted-for-tests)
alembic/         migrations
frontend/        SvelteKit app
docs/            OVERVIEW, research (evidence base), superpowers/specs + plans (the build log)
tests/           pytest suite (runs with no live API calls)
```

## Design Principles

### 1. State-driven
- **SQLite is the single source of truth.** Agents coordinate through shared, typed SQLModel state.
  They never call each other directly.
- **The `Assessment` table is the spine.** Every competence signal (self-explanation, decay/recall,
  calibration, teach-back, artifacts) derives from real, logged actions. Don't invent competence
  from anything that isn't a logged `Assessment` row.
- **`AgentEvent` is the observability trace.** It backs "What the agents did", a first-class UI
  surface, so treat it as product data. New agent actions should emit events.
- **Migrations for every schema change.** Use plain `op.add_column` on populated,
  FK-referenced tables. `batch_alter_table` recreates the table and breaks foreign keys on real
  data. Tests run with `PRAGMA foreign_keys=ON` for prod parity.

### 2. Agent specialization
- Each agent (Researcher, CurriculumDirector, Tutor, Assessor, and the engine capabilities above)
  has one clear responsibility and its own prompt(s) in `prompts.py`.
- New capabilities are added as new `engine/` modules without changing existing ones.

### 3. Enforcement in code
- Behaviors that matter for pedagogy or safety live in code paths, so they hold even when a prompt
  is coaxed: the gated `reveal_solution` tool (withhold solutions until an attempt is logged),
  SSRF-guarded artifact fetch, forced structured output. Don't move these into prompt text.

### 4. Pluggable, deterministically testable LLM layer
- The `llm/` client registry swaps the real Anthropic SDK for a **scripted** client. The whole
  agent crew is testable with **no live API calls**. Keep it that way. New LLM-backed code goes
  through the registry, never a direct SDK import in `engine/`.

### 5. Progressive enhancement
- MVP first, add complexity incrementally. Backward compatibility and data migrations for anything
  that touches persisted state.

## Development Workflow

**Spec-first, built in public.** Each capability starts as a design spec in
`docs/superpowers/specs/`, becomes a bite-sized plan in `docs/superpowers/plans/`, then ships via
subagent-driven development with adversarial code review. Those documents *are* the build log.

- **TDD:** write the failing test, watch it fail, then implement. Backend `just test`; frontend
  `cd frontend && npx vitest run`.
- **Feature branches**, clear commit messages, review before merge, tests green before merge.
- **Prompts are versioned** (`prompts.py` tags) so a behavior can be traced to the exact prompt.

## Quality & Privacy

- **Type-safe outputs:** all LLM interactions return validated structured output.
- **Local & private:** all learning records stay on the local machine; no telemetry. (Be honest that
  each AI call still ships its content to the model's provider. "Local-first" refers to *records*;
  inference is not offline.)
- **BYOK:** the app runs on the user's `ANTHROPIC_API_KEY`. Secrets live in `.env` (gitignored).
  Never commit keys or real user data.
- **Graceful degradation:** an agent failure should reduce functionality, not corrupt learning
  state.

## Performance Targets

- Agent response < 3s typical · state lookups < 100ms · keep a session's storage growth modest.
