# How Adaptive Academy works

## The goal

Most AI tutors try to give you a smooth answer as fast as possible. That can make you feel like
you understand something when you don't. The explanation was clear, but a week later you
can't do it on your own.

Adaptive Academy aims for the opposite: things you can still do later, without help. It does
this in two ways. The tutor won't hand you the answer until you've tried. And a concept only
counts as "solid" when several separate checks agree.

## What it does

The basic loop, with every agent's work visible:

1. **Research**: a Researcher searches from several angles at once and ranks real sources for
   a topic.
2. **Curriculum**: a Director turns those into a track, in phases, toward your goal.
3. **Tutor**: asks you questions instead of lecturing, and won't show a full solution until
   you've made an attempt. This is enforced in code (a gated `reveal_solution` tool), not just
   asked for in the prompt.
4. **Assess**: grades your work and updates what the app thinks you know.

On top of that loop:

- **Several checks, not one grade.** A concept is "solid" only when separate signals agree:
  explaining it in your own words, recalling it later, how well your confidence matched your
  grade, teaching it back, and things you build. Click any concept to see why it got its
  verdict.
- **Practice that makes it stick.** Decay checks (recall a concept cold, days later),
  productive failure (try a problem before you're shown how), calibration (guess how sure you
  are, then see the gap), and teach-back (explain it to someone else).
- **The Voyage.** A light, game-like view of your momentum: "wind" per topic and a Fleet of all
  your topics. It's based on your activity and kept separate from your grades on purpose, so a
  slow week never looks like failing.
- **Obsidian.** Use your vault notes as sources, and export concepts and tracks back as linked
  markdown.
- **Memory.** One local search index (SQLite full-text search, with optional vector search)
  covers your notes, sources, papers, answers, tutor replies, and generated questions. The
  tutor uses it and doesn't repeat what it already explained. Practice questions that are too
  close to old ones are rejected in code.
- **Concept graph and Scout.** Prerequisites between concepts are stored in SQLite and walked
  with plain SQL, no graph database. When you're stuck, the app points you at the weakest
  prerequisite. A Scout suggests new topics from gaps it notices, and you accept or dismiss
  each one.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  SvelteKit frontend (Svelte 5 / Tailwind 4)                  │
│  Dashboard · Today · Tutor · Practice · Teach · Retention ·  │
│  Map · Story · Fleet/Wayfinder · Programs                    │
└───────────────────────────┬──────────────────────────────────┘
                            │  REST (/api)
┌───────────────────────────┴──────────────────────────────────┐
│  FastAPI service                                             │
│                                                              │
│  engine/   research · curriculum · tutor · assess ·          │
│            decay · productive_failure · teach · momentum ·   │
│            progress · remediate · retention · story · vault ·│
│            memory · graph · scout                            │
│                                                              │
│  llm/      swappable model clients: Anthropic SDK,           │
│            Agent SDK, or scripted (for tests)                │
│                                                              │
│  prompts.py  every prompt, with a version tag that is        │
│              recorded with each agent action                 │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────┴──────────────────────────────────┐
│  SQLite (WAL) via SQLModel + Alembic: the single source of   │
│  truth. Assessment = every finished learning action, and     │
│  the basis for all five signals. AgentEvent = the agent log. │
└──────────────────────────────────────────────────────────────┘
```

**Design rules:**

- **Agents share state, they don't call each other.** They read and write the same SQLite
  tables. Every signal comes from the `Assessment` table, which only holds things you actually
  did. That's what keeps the "what you know" picture honest.
- **You can see what happened.** Every agent action is logged (`AgentEvent`), and "What the
  agents did" is part of the UI. Prompts carry version tags, so you can trace a behaviour back
  to the prompt that caused it.
- **Testable without an API key.** The model client can be swapped for a scripted one, so the
  whole test suite runs without calling a real model.
- **Rules live in code.** Holding back solutions and the safety checks on fetched links are
  code paths, not prompt instructions, so they hold however a prompt is worded.

## Stack

Python 3.12, FastAPI, SQLModel, SQLite (WAL), Alembic, and the Anthropic SDK. SvelteKit 2,
Svelte 5, and Tailwind 4. `uv` for packages and `just` for tasks. Apache-2.0.

## Cost and privacy

It runs on your own API key, and several agents work together, so a busy session costs real
money ([Costs](COSTS.md)). Your records stay on your machine, but each AI request goes to
Anthropic. It's pre-1.0.

---

Setup is in the [README](../README.md). The design specs are in
[`docs/superpowers/specs/`](superpowers/specs/), and the research behind them is in
[`docs/research/`](research/).
