# Adaptive Academy

**An open-source, local-first AI learning tool for serious self-directed adult learners — grounded in learning science, with an observable multi-agent spine instead of one opaque chatbot.**

## The goal

Most "AI tutors" optimize for a frictionless answer. That produces the *illusion* of
competence: you feel like you understand because the model explained it well, but you can't
reproduce it cold a week later. Adaptive Academy optimizes for the opposite — **durable,
unassisted, delayed performance** — by refusing to hand you answers until you've generated an
attempt, and by only calling a concept "solid" when several independent signals agree.

It exists to help people learn *deeply* by building and shipping, and to do it in the open. Your
records stay on your machine; you bring your own Anthropic key.

## What it does

A complete learning loop, with every agent's work visible:

1. **Research** — a fan-out Researcher gathers and tiers real sources for a topic.
2. **Curriculum** — a Director turns those into a phased track toward a "North Star" goal.
3. **Tutor** — guides you Socratically, and **withholds full solutions until you've logged an
   attempt** — enforced in code (a gated `reveal_solution` tool), not just asked for in a prompt.
4. **Assess** — grades your work and feeds a competence model.

On top of that loop sit the research-grounded mechanics that make learning *stick*:

- **Anti-Goodhart competence triangulation** — a concept is "solid" only when multiple independent
  signals agree: graded self-explanation, spaced decay/recall, calibration accuracy, teach-back,
  and shipped artifacts. Never a single grade. (You can expand any concept to see *why* it got its
  verdict.)
- **Solidification features** — Decay Checks (spaced cold recall), Productive Failure (struggle
  before instruction), a Calibration Loop (predict → confront the gap), and Teach-It (the protégé
  effect).
- **The Voyage** — a forgiving, game-like momentum layer ("wind" per topic + a cross-topic Fleet)
  that models whether you *keep going*, derived from your real activity and kept deliberately
  independent of competence, so a slump never reads as failure.
- **Local-first interop** — ingest your Obsidian vault notes as grounding sources, and export
  concepts/tracks back out as linked markdown.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  SvelteKit frontend (Svelte 5 / Tailwind 4)                  │
│  Dashboard · Today loop · Tutor · Practice · Teach ·         │
│  Retention · Map · Story · Fleet/Wayfinder (the Voyage)      │
└───────────────────────────┬──────────────────────────────────┘
                            │  REST (/api)
┌───────────────────────────┴──────────────────────────────────┐
│  FastAPI service                                             │
│                                                              │
│  engine/   research · curriculum · tutor · assess ·          │
│            decay · productive_failure · teach · momentum ·   │
│            progress · remediate · retention · story · vault  │
│                                                              │
│  llm/      pluggable client registry — Anthropic SDK /       │
│            agent-SDK / scripted (deterministic tests).       │
│            Forced structured output; injection-demarcated.   │
│                                                              │
│  prompts.py  version-tagged prompt registry (poor-man's      │
│              Langfuse) — every tag traced into AgentEvent    │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────┐
│  SQLite (WAL) via SQLModel + Alembic — single source of      │
│  truth. Assessment table = unified record of every completed │
│  learning action and the substrate for all 5 signals.        │
│  AgentEvent table = the observability trace.                 │
└──────────────────────────────────────────────────────────────┘
```

**Key design commitments:**

- **State-driven, not call-driven** — agents coordinate through shared SQLite state (typed
  SQLModel models), never direct calls. The `Assessment` table is the spine: every signal derives
  from real, logged actions, which is what keeps the competence model honest.
- **Observable by construction** — every agent action is traced (`AgentEvent`); "What the agents
  did" is a first-class UI surface, not a debug log. Prompts are version-tagged so you can trace a
  behavior back to the exact prompt that produced it.
- **Pluggable LLM layer** — a client registry swaps the real Anthropic SDK for a scripted client,
  so the whole agent crew is testable deterministically (the test suite runs with no live API
  calls).
- **Enforcement in code, not vibes** — the generation-first stance (withhold solutions,
  SSRF-guarded artifact fetch, etc.) lives in code paths, so it holds even when a prompt is coaxed.

## Stack

Python 3.12 · FastAPI · SQLModel · SQLite (WAL) · Alembic · Anthropic SDK ·
SvelteKit 2 / Svelte 5 / Tailwind 4. Package manager `uv`, task runner `just`. Apache-2.0.

## Honest framing

BYOK and multi-agent: a rich session spends real tokens (a few dollars), and while your *records*
stay local, each AI call still goes to Anthropic. "Local-first" means your data lives on your
machine — not that inference is offline. It's pre-1.0 and built in public.

---

See [`README.md`](../README.md) for setup and run instructions, and
[`docs/superpowers/specs/`](superpowers/specs/) for the design spec and learning-science evidence
base.
