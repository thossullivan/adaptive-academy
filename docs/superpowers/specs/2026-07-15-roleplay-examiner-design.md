# Roleplay / Examiner Mode — Design Spec

**Date:** 2026-07-15
**Status:** Approved for planning

## Goal

Add a general **Roleplay / Examiner mode**: persona-driven adversarial dialogue (skeptical
buyer, staff engineer in a design review, thesis committee, …) that is **auto-generated from a
Program milestone**, sparred text-first, then **blind-graded against the milestone's rubric** so
each session produces **per-concept gate evidence**. It works identically for technical and
non-technical Programs — the domain is just the persona and the rubric.

## Why

Deliberate practice — retrieve/generate under pressure, get scored, repeat — is the spine of the
tool, but the *adversarial-dialogue* slice of practice (defend a design under pushback, run a
discovery call, survive a viva) has no home yet. It is exactly the slice that distinguishes
durable depth from fluent recall: can you hold up your understanding when something pushes back?
The market for this (Hyperbound et al.) is all cloud SaaS at $100+/user/mo with no self-hosted
option — so a BYOK, self-hosted, generation-first version wired into a personal learning map is
genuinely differentiated.

## Scope

**In:** text-first roleplay against a materialized milestone; scenario director; persona loop;
blind anchored grader writing per-concept `Assessment` rows; API; UI; migration; tests.

**Out (deferred):** voice (STT/TTS) — the design leaves a clean seam; ungraded/pre-materialization
"free spar"; multi-persona panels (a single persona per session in v1); learner-authored personas.

## Architecture

Chosen approach: **extend the existing dialogue engine, with dedicated leaf tables.** Roleplay
reuses the substantial plumbing — the 3-backend `LLMClient.complete` loop, `AgentEvent` tracing,
transcript-history construction, and the `assess.py` anchored/anti-sycophancy grading — but stores
its transcript in its **own leaf tables** so nothing in the tutor's `Conversation`/`Message` path
is destabilized (no nullable-FK gymnastics, no `Message`-table rebuild).

```
Spar (materialized milestone)
      │
      ▼
[1] Scenario Director  ── ROLEPLAY_DIRECTOR ──►  persona_brief (JSON)      status: briefing→active
      │                    reads milestone.success_criteria
      │                    + load-bearing concepts (+ estimates)
      ▼
[2] Persona Loop       ── ROLEPLAY_PERSONA ──►   RoleplayTurn(role=persona) status: active
      │  run_roleplay_turn(text_in) -> text_out  (no tools; LLMClient.complete; all 3 backends)
      │  actor with a goal; hidden objections; never breaks character
      ▼
[3] End: user "End & score me" | persona end-signal | turn cap (~15)        status: active→ended
      │
      ▼
[4] Blind Grader       ── ROLEPLAY_GRADE ──►     Assessment(kind="roleplay") per concept
         separate pass (NOT the persona); assess.py anchored score           status: ended→graded
         + deterministic omission/misconception ceilings
         → per-concept gate evidence + outcome summary
```

**The three-part anti-sycophancy guard** (the crux): (1) the persona is an *actor with a goal*,
told not to concede without earned reasons and never to reveal grading exists; (2) grading is a
*separate blind pass* under the deterministic `assess.py` ceilings that cannot be charmed; (3)
difficulty is *pinned to current concept estimates* via `compute_levels` (expertise-reversal:
don't crush a novice, don't coddle an expert).

**Voice seam:** the text turn boundary. `run_roleplay_turn(text_in) -> text_out` +
`RoleplayTurn` persistence. A later voice loop wraps `STT(audio)→text_in` and
`text_out→TTS(audio)` — even with a different provider — leaving session, persona, and grader
untouched.

## Components

### Units and responsibilities

| Unit | Responsibility | Depends on |
|------|----------------|-----------|
| `RoleplaySession` / `RoleplayTurn` (models) | Session state + transcript | `Program`, `Milestone` |
| `engine/roleplay.py::direct` | Generate `persona_brief` from milestone + concepts | LLM registry, `gates.milestone_load_bearing`, `compute_levels`, `ROLEPLAY_DIRECTOR` |
| `engine/roleplay.py::run_roleplay_turn` | One persona turn; persist; trace | LLM registry (`.complete`), `ROLEPLAY_PERSONA` |
| `engine/roleplay.py::grade_roleplay` | Blind per-concept grading → `Assessment` rows | `assess.py` scoring, `ROLEPLAY_GRADE` |
| `api/routes_roleplay.py` | REST surface | the engine, `deps` |
| prompts (`ROLEPLAY_DIRECTOR`, `ROLEPLAY_PERSONA`, `ROLEPLAY_GRADE`) | Version-tagged prompt text | `prompts.py` registry |
| Frontend `/roleplay/[sid]` + milestone "Spar" entry | Chat UI + scorecard | tutor chat component, UI kit |

### Backends

Because the persona uses **no tools**, a single `run_roleplay_turn` on `LLMClient.complete`
works across **anthropic, agent_sdk (`AgentSDKLLMClient` already implements `.complete`), and
scripted** — no separate `_sdk` path (unlike the tutor, which needed one only for gated
in-process tool use).

## Data Model

Two new leaf tables (created fresh — no ALTER of existing tables) and two additive nullable
columns.

**`RoleplaySession`**
- `id: int (pk)`
- `program_id: int (fk program.id)`
- `milestone_id: int (fk milestone.id)`
- `status: str` — `"briefing" | "active" | "ended" | "graded"`
- `persona_brief: JSON` — `{persona, goal, situation, hidden_objections: [str], win_conditions: [str], difficulty: str}`
- `outcome: JSON | null` — `{result: str, summary: str}` (natural result + narrative; set at grade time)
- `created_at`, `updated_at: datetime`

**`RoleplayTurn`**
- `id: int (pk)`
- `session_id: int (fk roleplaysession.id)`
- `role: str` — `"user" | "persona"`
- `content: str`
- `created_at: datetime`

**Additive columns (plain `add_column`, nullable):**
- `Assessment.roleplay_session_id: int | null (fk roleplaysession.id)` — traces each piece of
  gate evidence back to its spar. `Assessment.kind` gains the value `"roleplay"` (no schema
  change — `kind` is free text).
- `AgentEvent.roleplay_session_id: int | null (fk roleplaysession.id)` — observability trace,
  mirroring the existing `program_id` / `conversation_id` links.

**Availability rule:** a milestone can be sparred only once its topic is materialized and has
load-bearing concepts (via existing lazy-start), so the grader has concepts to credit. Before
that, "Spar" returns 400 with a "start the topic first" message.

**Public vs hidden brief:** the API exposes only `persona` + `situation` to the client during a
session. `hidden_objections` and `win_conditions` are withheld until after grading (so discovery
is real), then may be surfaced in the scorecard.

## Data Flow (per stage)

1. **Brief.** `POST …/roleplay` → create `RoleplaySession(status="briefing")`; `direct()` runs
   `ROLEPLAY_DIRECTOR` over `milestone.success_criteria` + load-bearing concept names/estimates →
   `persona_brief`; `status="active"`; return public brief.
2. **Spar.** `POST /api/roleplay/{sid}/turns` with user text → persist `RoleplayTurn(role="user")`;
   `run_roleplay_turn` builds the persona system prompt from the brief, feeds transcript history,
   calls `LLMClient.complete` (no tools) → persist `RoleplayTurn(role="persona")`; return reply +
   status. Status may flip to `ended` if the persona emits its structured end-signal or the turn
   cap (~15 user turns) is reached.
3. **End.** `POST /api/roleplay/{sid}/end` (or auto on end-signal/cap) → `status="ended"`.
4. **Grade.** Grader reads full transcript + rubric + load-bearing concepts; attributes dialogue
   evidence to each concept; runs the **existing `assess.py`** path (LLM band under deterministic
   omission/misconception ceilings); writes one `Assessment(kind="roleplay",
   roleplay_session_id=…)` per concept touched (score, gaps, verdict); writes `outcome`;
   `status="graded"`. Evidence is picked up by gates automatically (they already read
   `Assessment`).

## API

- `POST /api/programs/{pid}/milestones/{mid}/roleplay` → `{session_id, status, brief_public, turns: []}`; 400 if no materialized concepts.
- `POST /api/roleplay/{sid}/turns` `{content}` → `{reply, status}`.
- `POST /api/roleplay/{sid}/end` → `{status:"graded", outcome, scorecard:[{concept_id, concept, score, verdict, gaps}]}`.
- `GET /api/roleplay/{sid}` → `{status, brief_public, turns, outcome|null, scorecard|null}`.
- `GET /api/programs/{pid}/milestones/{mid}/roleplay` → past sessions (id, created_at, status, outcome summary).

Backend selection follows existing `deps` (`get_llm` / `use_agent_sdk`); no roleplay-specific
branching needed since there are no tools.

## UI

- **Entry:** a **"Spar"** action on the milestone (program detail / milestone view), enabled only
  when the topic is materialized. Disabled state links to "start the topic."
- **Roleplay page `/roleplay/[sid]`:** reuse the tutor chat component + Observatory dark theme.
  Header shows persona + situation (public brief). Transcript + input box + **"End & score me."**
- **After grading:** outcome banner + a **per-concept scorecard** (score, verdict, gaps, "what to
  drill") with a link back to the milestone gate so the spar visibly moves the gate. Optionally
  reveal the previously-hidden objections/win-conditions as a debrief.
- **History:** past spars listed on the milestone with outcome summaries.

## Error Handling

- Director / persona / grade LLM failures ride the existing `anthropic.APIError → 502` handler
  (and `AgentSDKError → 502`). No new global handlers.
- A failed grade leaves `status="ended"` (transcript preserved, re-gradable) — never lost.
- Turn cap reached → auto-`ended`; the next `end` (or an auto-trigger) grades.
- Director failure → no active session left dangling: session stays `briefing` and is re-runnable
  / discardable.

## Testing (TDD, scripted backend — zero live API)

Add scripted director/persona/grader fixtures so the whole flow is deterministic (extends the
existing `scripted_*` clients). Cases:

1. `direct()` produces a well-formed `persona_brief` from a milestone (persona, goal, hidden
   objections, win conditions, difficulty).
2. Persona loop persists `user` + `persona` turns in order; history is rebuilt correctly.
3. Termination: (a) persona end-signal flips `status=ended`; (b) turn cap flips `status=ended`.
4. Grader writes exactly one `Assessment(kind="roleplay", roleplay_session_id=…)` per
   load-bearing concept, **with the deterministic ceilings applied** (omission/misconception caps
   from `assess.py`).
5. Gate: the milestone's gate report reflects the new roleplay evidence.
6. Availability rule: milestone with no materialized concepts → `POST …/roleplay` returns 400.
7. Grade-failure path: transcript preserved, `status="ended"`, re-gradable.

`conftest` retains `PRAGMA foreign_keys=ON` (prod parity). One **additive** Alembic migration —
`create_table` × 2 + `add_column` × 2 (all nullable), **no `batch_alter_table`** — accompanied by
the populated-DB regression test pattern (seed prior revision with referencing rows, run the real
migration via subprocess alembic, assert success).

## Migration

Single revision:
- `op.create_table("roleplaysession", …)`
- `op.create_table("roleplayturn", …)`
- `op.add_column("assessment", sa.Column("roleplay_session_id", sa.Integer(), sa.ForeignKey("roleplaysession.id"), nullable=True))`
- `op.add_column("agentevent", sa.Column("roleplay_session_id", sa.Integer(), sa.ForeignKey("roleplaysession.id"), nullable=True))`

All additive; safe on the populated container DB.

## Open questions / future

- Voice loop (separate spec) — the seam is defined above.
- Multi-persona panels (committee of 3) — v2; the single-persona brief generalizes to a list.
- Weighting roleplay evidence vs. other signals in the gate — start with parity (one
  `Assessment` like any other); revisit if spars over- or under-count.
