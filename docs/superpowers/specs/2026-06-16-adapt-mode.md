# CurriculumDirector Adapt-Mode (Remediation) — Spec

**Date:** 2026-06-16
**Milestone:** Plan 5
**Status:** Approved (focused milestone spec; decisions below)

## 1. Goal

Close the adaptive loop. When the Assessor flags a gap — a `Concept` whose latest
`Assessment` recorded specific `gaps[]` and whose `KnowledgeEstimate` dropped — the
**CurriculumDirector**, in *adapt mode*, injects a **targeted remediation** into the
existing `Track`: one or more low-assistance, project/problem-first `Item`s addressing
those exact gaps (plus, optionally, a spaced revisit of the gap concept in a later phase).
Keyed on prior knowledge + the specific gaps, not raw quiz difficulty (v1 spec §4.3). This
makes the system adaptive end-to-end: research → curriculum → tutor → assess → **re-plan**.

## 2. Locked decisions (deviations / choices)

These resolve the two open questions flagged at the close of Plan 4. They are deliberate
v1 scoping choices, consistent with the confirm-tier / human-in-the-loop philosophy.

- **§2.1 Manual, explicit trigger (not automatic).** Remediation runs only when the user
  invokes `POST /api/concepts/{id}/remediate` (surfaced as a "Remediate" affordance right
  after a weak assessment). The Assessor does **not** auto-remediate on every probe. This
  keeps the human in the loop and mirrors the existing confirm-tier pattern. Automatic
  remediation is deferred (Plan 6+).
- **§2.2 Inject, don't re-sequence.** Adapt mode *appends* targeted items into an existing
  phase; it never reorders phases, never deletes, and never overwrites user-edited content.
  True phase re-sequencing is much harder to make non-destructive and is deferred. This is
  the same "code-enforced, additive" discipline as Plan 1's attempt-gate, Plan 2's rank,
  Plan 3's spaced-revisit, and Plan 4's rules layer.
- **§2.3 Remediation marker = one additive column.** `Item` gains
  `added_by: str = "curriculum"` (mirrors `SourceDoc.added_by`). Remediation items are
  written with `added_by = "remediation"`. This is the distinguishable flag the UI keys on
  and the guarantee that we only ever *append* such items. A second additive column,
  `remediation_key: str = ""`, carries the idempotency signature (see §2.4). Both are
  additive `ALTER TABLE ADD COLUMN` (native SQLite, no table recreation — `item.id` is
  FK-referenced by `assessment.item_id`, but adding columns does not recreate the table).
- **§2.4 Idempotency is per-gap, keyed by a normalized gap signature.** Each open gap maps
  to a stable `gap_key` (lowercased, whitespace-collapsed, trimmed). A remediation item
  carries `remediation_key = gap_key(gap)`. Before injecting, the engine collects the
  `remediation_key`s of existing **open** (status ∈ {todo, doing}) remediation items for
  the concept; any gap whose key is already covered is skipped. Re-running for the same
  still-unresolved gap injects nothing; a *new* gap from a later assessment is injected even
  while an old remediation item is still open. The optional spaced revisit uses a distinct
  deterministic key (`revisit:{concept}`) so it is likewise injected at most once.
- **§2.5 Placement heuristic ("current or next phase").** The "current phase" is the
  earliest phase (by `position`) that still has at least one non-`done` item; if every item
  is done (or a phase has no items), fall back to the last phase. Remediation items are
  appended to that phase. The optional spaced revisit is appended to the *next* phase after
  the target if one exists, else the target phase. Pure and deterministic.
- **§2.6 Markdown round-trip drops the marker (accepted limitation).** Like `concept_refs`
  and `links` (already DB-only since Plan 3), `added_by` / `remediation_key` are **not**
  serialized to the canonical markdown. Exporting then re-importing a track turns a
  remediation item back into a normal curriculum item. This is consistent with the existing
  "canonical subset" round-trip contract; the round-trip must not crash and must preserve
  item text/type/status/structure with remediation items present.
- **§2.7 One LLM call per remediation** (no fan-out), behind the existing `LLMClient`
  Protocol — testable with `ScriptedLLMClient`. Mirrors Plan 3/4.

## 3. Behaviour

### 3.1 Endpoint

`POST /api/concepts/{concept_id}/remediate`

- Body: `{ "from_assessment_id": int | null }` (null → use the concept's latest assessment).
- `404` if the concept does not exist.
- `400` ("no assessment to remediate from") if no assessment is found for the concept.
- `200` → `{ "items": [ItemOut...], "events": [EventOut...] }` where `items` are the
  newly-injected remediation items (empty list if everything was already covered).

### 3.2 Engine flow (`engine/remediate.py`)

```
load latest Assessment (gaps, score) ──► 400 if none
load KnowledgeEstimate (level)
collect open remediation_keys for concept  (status in {todo,doing}, added_by="remediation")
open_gaps = [g for g in assessment.gaps if gap_key(g) not in covered]
if not open_gaps:
    emit remediate:noop ; return RemediationResult(items=[], events)
single LLM call (system+user) ──► RemediationDraft{items:[{type,text}], revisit:{text}|null}
plan_remediation_items(draft, concept, open_gaps, covered) ──► one item per open gap
choose_target_phase(phases) ──► append items (added_by="remediation", remediation_key,
                                concept_refs=[concept.name], type, position=end)
if draft.revisit and "revisit:{concept}" not covered: append revisit to a later phase
emit remediate:probe / remediate:generated / remediate:placed / remediate:done
commit ; return RemediationResult(items, events)
```

- **Evidence-keyed prompt** (`_REMEDIATE_SYSTEM`): default LOW-ASSISTANCE,
  PROJECT/PROBLEM-FIRST items (expertise-reversal); each item targets a *named gap*;
  deliberate-practice drills are SUPPORTING, never the spine; keyed on the learner's
  estimate level (prior knowledge), not raw difficulty. Returns ONLY JSON:
  `{"items": [{"type": "read"|"build"|"write", "text": str}], "revisit": {"text": str}|null}`.
- **Pure, deterministic, unit-tested helpers:** `gap_key`, `plan_remediation_items`
  (idempotency filter + per-gap item assignment with deterministic fallback text when the
  LLM returns fewer items than gaps), `choose_target_phase`, `parse_remediation_json`,
  `build_remediate_prompt`.
- **Observability:** one `AgentEvent` (topic-scoped) per step.

### 3.3 Surfacing

- `ItemOut` gains `is_remediation: bool` (derived from `added_by == "remediation"`). Every
  builder of `ItemOut` sets it (`_curriculum_out`, `patch_item`).
- Track UI flags remediation items (chip + amber tint).
- The assess result panel shows a **"Remediate"** button when the result has gaps; it calls
  `POST .../remediate` and links to the track.

## 4. Out of scope (Plan 6+)

Full phase re-sequencing/reordering; automatic un-prompted remediation; Assessor fan-out +
`source_quiz`/`ReferenceAnchor` wiring; delayed/surprise scheduling daemon; build-in-public
log; streaming; auth.

## 5. Definition of done

- `POST /api/concepts/{id}/remediate` reads the latest Assessment + estimate and injects
  targeted items into the current/next phase; `400` cleanly with no assessment.
- Evidence-keyed (low-assistance/project-first; addresses named gaps; drills supporting).
- Non-destructive + idempotent: items marked `added_by="remediation"`; never delete/overwrite
  user content; re-running for the same unresolved gap does not duplicate (deterministic
  unit test).
- Surfaced + editable in `/topics/[id]/track` flagged as remediation; markdown round-trip
  still holds with remediation items present.
- Full loop demonstrable: integration test research → curriculum → tutor → weak assess →
  remediate asserts a targeted remediation item referencing the gap concept now exists.
- One `AgentEvent` per step; generation tested with a scripted client; inject/placement/
  idempotency logic pure & unit-tested; Plans 1–4 paths intact; additive migration
  round-trips clean + after-seed.
