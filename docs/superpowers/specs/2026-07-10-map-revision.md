---
title: Map Revision — learnings-aware re-research and freshness for Programs
created: 2026-07-10
status: approved for planning
companion_to:
  - 2026-07-09-program-layer.md
---

# Map Revision

## 1. Problem & goal

A Program's milestone map is drawn once, at creation, from a single research pass.
Two things erode it over a months-to-years horizon:

1. **Learnings.** Gate evidence, knowledge estimates, and completed legs change what
   the remaining map should look like — a planned topic may be verifiably known, a
   weak gate may deserve a new supporting topic.
2. **Field drift.** The focus area (custom LLMs, in the motivating program) moves
   fast; a map drawn in mid-2026 will mis-plan legs started in 2027.

Topic-level content is already fresh by construction (research runs when a topic is
**started**, per the Program layer's lazy materialization). This spec covers the
remaining gap: **revising the program map itself**, grounded in accumulated learnings
and in what has changed in the field since the map was last drawn.

## 2. Key decisions

1. **Scope: program map only.** Milestones and planned topics. Mid-topic source
   refresh is out of scope (an in-progress topic's gaps are already served by the
   remediation flow).
2. **Trigger: milestone boundaries + manual.** A "Revise map" action is always
   available; the UI nudges when a gate flips to passed (the moment learnings are
   richest). No scheduled/background compute — the app is local-first and not
   always running, and revisions are paid research passes.
3. **Output: a reviewed diff, additive-first.** The reviser proposes *changes*
   (add/revise/prune), each accepted or rejected individually. Started or passed
   work is untouchable — enforced in code at parse time AND apply time, in the
   project's attempt-gate/spaced-revisit tradition of code-enforced invariants.
   Prunes apply only to un-started items and never delete rows.
4. **Revision = the research muscle re-aimed.** Reuses `fan_out_with_retry` (with
   its second-chance sweep and diagnosable errors) and the forced-tool-use
   synthesis pattern; a deterministic **learnings digest** (no LLM) carries the
   evidence into the prompt.
5. **This retires the "no regenerate path" gap.** A revision run on a
   barely-started program is effectively a regenerate; the once-only guard on
   initial research stays.

## 3. Data model (additive)

- **`MapRevision`** — `id`, `program_id` FK, `map_health` (one-paragraph field
  summary), `created_at`. The newest row's `created_at` is "when the map was last
  revised" (falls back to program creation for the first pass).
- **`MapChange`** — `id`, `revision_id` FK, `kind`
  (`add_topic | add_milestone | revise_milestone | prune_topic | prune_milestone`),
  `payload` (JSON: kind-specific fields, see §4.3), `why` (text), `source_urls`
  (JSON list), `status` (`proposed | accepted | rejected`), `created_at`.
- **`Milestone.archived`** (bool, default false) — pruned milestones are archived,
  never deleted; archived milestones are hidden from the rail and excluded from
  DAG ordering and gate evaluation.
- **`ProgramTopicLink.added_by`** (`"research" | "revision"`, default `"research"`)
  — provenance, mirroring `Item.added_by` from the remediation work.

One additive migration covers the two new tables and two new columns.

## 4. Flows

### 4.1 Learnings digest (pure)

`engine/revision.py::build_learnings_digest(session, program) -> str` — a compact,
deterministic serialization of: per milestone (in order): title, gate status,
started/stub/pruned topic counts, and for started legs the per-concept evidence
verdicts from `engine/gates.py` (`verified | stale | weak_artifact |
never_probed_cold`); plus program-wide alias-group knowledge levels. No LLM call;
unit-testable as a pure function over seeded rows.

### 4.2 Revision pass

`POST /api/programs/{id}/revise`:

1. Guard: 400 if an open revision (any `MapChange.status == "proposed"`) exists —
   resolve the current diff before running another paid pass.
2. Fan out 3 revision angles via `fan_out_with_retry` (all trace events carry
   `program_id`; kinds `program_revision:plan / subagent / subagent_retry /
   subagent_error`):
   - `whats_new` — "important developments in {focus_area} since {last-revision
     month year}"
   - `curricula_check` — changes in canonical curricula / quals syllabi for the goal
   - `frontier_shifts` — new architecture families / results that would change a
     1–2 year study plan
3. Zero-sources guard: reused from initial research — commit trace, raise
   (→ legible 400), persist nothing.
4. Synthesis: one forced-tool-use call (`PROGRAM_REVISION` prompt, version-tagged,
   tag emitted as an `AgentEvent(kind="prompt")`). Input: current map serialized
   WITH statuses (so the model knows what is untouchable), the learnings digest,
   and the fresh sources. Output schema: `{map_health: str, changes: [...]}`.
5. **Parse-time validation (code-enforced):** drop any change that (a) targets a
   started or passed milestone with `revise_milestone`/`prune_milestone`, (b)
   prunes a started topic link, (c) references an unresolvable milestone/link, or
   (d) duplicates an existing un-started link title (case-insensitive) with
   `add_topic`. Dropped changes are counted in a
   `program_revision:changes_dropped` trace event.
6. Persist `MapRevision` + surviving `MapChange` rows (all `proposed`) in one
   transaction. Nothing is applied.

### 4.3 Change kinds & apply semantics

`POST /api/programs/{pid}/changes/{change_id}/accept` applies immediately and
atomically (single commit); `/reject` just flips status. Both 404 on cross-program
ids and 400 on already-resolved changes. Apply re-validates the §4.2.5 rules
against *current* state (the map may have changed since the pass).

- `add_topic` `{milestone_id, title, why}` → new `ProgramTopicLink(status="stub",
  added_by="revision")`.
- `add_milestone` `{after_milestone_id | null, title, success_criteria,
  topics: [{title, why}]}` → new `Milestone` (order_index slotted after the named
  leg, subsequent legs shifted) + its links as stubs (`added_by="revision"`).
- `revise_milestone` `{milestone_id, title?, success_criteria?}` → in-place update;
  un-started legs only.
- `prune_topic` `{link_id}` → `status="pruned"` (reversible by hand; never deleted).
- `prune_milestone` `{milestone_id}` → `archived=true`; only when it has no started
  links; excluded thereafter from rail, DAG, and gates.

### 4.4 Nudge

`engine/gates.py::milestone_gate` emits `AgentEvent(program_id=...,
kind="program:gate_passed")` when (and only when) `gate_status` transitions to
`passed`. `ProgramDetailOut` gains `revision_suggested: bool` — true iff a
`gate_passed` event postdates the newest `MapRevision` (or exists when there is
none). UI: a quiet banner on `/programs/[id]` and the Today program strip ("Leg
verified — revise the map with what you've learned?"). Nag, never block.

## 5. UI

- `/programs/[id]`: a **Revision panel** when an open revision exists — the
  `map_health` paragraph, then one card per proposed change (kind badge, human
  rendering of the payload, `why`, source links) with Accept / Reject buttons.
  A "Revise map" action (busy-guarded) sits in the page header; disabled with an
  explanatory tooltip while a revision is open.
- Revision-added links show a small provenance chip (like remediation items on the
  track page). Archived milestones are hidden behind a "show archived" toggle.
- The `revision_suggested` banner on the program page and Today strip.

## 6. Errors & resilience

- Fan-out inherits the retry sweep + message-bearing `subagent_error` events.
- Synthesis/API faults surface via the existing legible-error handlers (502) or
  ValueError→400 mapping; an aborted pass persists nothing but trace events.
- Accept/reject are pure DB mutations — no LLM fault modes.

## 7. Testing

- Digest: pure-function matrix over seeded programs (statuses, verdicts, empty).
- Parse validation: each §4.2.5 drop rule; dropped-changes trace event.
- Apply: each change kind round-trips; re-validation catches a change staled by an
  intervening apply (e.g. milestone started between pass and accept → 400);
  archived milestone excluded from gate evaluation and DAG.
- Nudge: gate flip emits once (not on re-evaluation without transition);
  `revision_suggested` truth table vs MapRevision timestamps.
- End-to-end scripted loop: seed program with one passed leg → revise (scripted
  researcher + LLM) → accept an `add_topic` and a `prune_topic`, reject one →
  map reflects exactly the accepted changes.
- Migration round-trips clean + after-seed, per convention.

## 8. Non-goals

- Mid-topic source refresh (existing remediation/sources flow covers in-progress
  topic gaps).
- Auto-apply, scheduled/background revision, or time-based staleness nags.
- Program deletion (separate backlog item).
- Revision history UI beyond the open diff (rows are kept; a browsing UI can come
  later if wanted).

## 9. Open questions (carried into planning)

- Whether `add_milestone` should also propose `depends_on` edges (default: new leg
  depends on the leg it slots after; richer edges deferred).
- Digest size bounds for very large programs (start unbounded; revisit if prompts
  bloat).
