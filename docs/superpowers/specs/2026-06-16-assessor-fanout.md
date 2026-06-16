# Assessor Fan-out — Source-Grounded Anchors + source_quiz Wiring — Spec

**Date:** 2026-06-16
**Milestone:** Plan 6
**Status:** Approved (focused milestone spec; user approved scope "A + v1 of C")

## 1. Goal

Strengthen the Assessor's anchoring by giving it **ground truth the grader did not invent**.
Today both the rubric *and* the grade come from the same LLM; the `must_include` rules layer
helps but those terms are themselves model-generated. This milestone fans out over the
learner's **accepted `SourceDoc`s** (one parallel subagent each, reusing Plan 2's muscle) to
generate **`ReferenceAnchor`s** — a source-attributed question + reference answer + key
points — then **wires the dormant `source_quiz` probe** so `assess_concept` grades a learner's
answer *against the anchor* instead of a self-generated rubric. A thin navigation slice
surfaces which concepts now have a source-grounded quiz available.

The decision that shapes this build (agreed in brainstorming): **fan-out parallelizes
generation, not grading.** Grading needs the learner's response and stays the existing serial,
anchored path. So we fan out anchor *generation*; the learner takes the quiz one item at a time.

## 2. Locked decisions

- **§2.1 Fan-out unit = accepted SourceDoc.** One subagent per accepted source generates that
  source's anchors, concurrently (`ThreadPoolExecutor` + `as_completed`, results collected in
  source order for deterministic tracing) — a direct mirror of Plan 2's Researcher fan-out.
- **§2.2 Dedicated client seam (mirror Plan 2).** A new `AnchorClient` Protocol
  (`generate(brief: AnchorBrief) -> list[RawAnchor]`) with a thread-safe, **by-source-keyed**
  scripted test double (`ScriptedAnchorClient`) and a real `AnthropicAnchorClient` (structured
  LLM call per source). Keying the double by source (not by a shared queue) keeps tests
  deterministic under concurrency — the same reason Plan 2 keyed its double by angle.
- **§2.3 Anchors are grounded in the source's stored metadata (summary/title/url) + the
  topic's key concepts — NOT full source text** (we don't store full text). This is an honest,
  documented limitation: the anchor is still *source-attributed* and generated at a different
  time than grading, so it is meaningfully less self-referential than the rubric, but it is not
  a verbatim-from-source ground truth. Full-text fetch is deferred.
- **§2.4 Concept linking by name match.** Each `RawAnchor` carries a `concept_name`; the
  orchestrator links it to a `Concept` (case-insensitive exact match against the topic's
  concepts). No match → anchor is still stored with `concept_id = None` (usable topic-wide,
  just not surfaced per-concept).
- **§2.5 Idempotent generation.** Anchors dedupe on `(source_doc_id, normalized question)`;
  re-running generation does not duplicate (deterministic, unit-tested — parallels Plan 2
  dedup / Plan 5 idempotency).
- **§2.6 source_quiz grades against the anchor.** A new branch in `assess_concept`: for
  `kind == "source_quiz"`, resolve a `ReferenceAnchor` (explicit `anchor_id`, else the
  lowest-id anchor for the concept; **raise → HTTP 400 if none**), then grade with
  `probe = anchor.question`, `reference = anchor.reference_answer`,
  `criteria = must_include = anchor.key_points` (key_points feed the deterministic
  anti-sycophancy rules layer), `rubric_id = None`, and persist `Assessment.anchor_id`. No
  rubric is generated for source_quiz. (Anchors carry no `weak_signs`, so the deterministic
  *misconception* check is rubric-only; the omission/anti-sycophancy check still fires via
  `key_points`. An explicit `anchor_id` that belongs to a *different* concept is rejected —
  topic-wide anchors with `concept_id = None` are allowed for any concept.)
- **§2.7 Navigation (v1 slice of C).** `ConceptOut` gains `has_anchor: bool` (computed). The
  assess UI re-enables the **Source quiz** probe *only* for concepts that have an anchor,
  pre-filling the anchor's question. No heatmap; no track-wide sweep.
- **§2.8 No migration.** `ReferenceAnchor` and `Assessment.anchor_id` already exist (Plan 4).
  `has_anchor` and `anchor_id` are API-only (computed field / request param). Plans 1–5 paths
  remain intact.
- **§2.9 Single structured LLM call per source** behind the Protocol — testable with the
  scripted double; no network in tests.

## 3. Behaviour

### 3.1 Endpoints

- `POST /api/topics/{topic_id}/anchors` → fan out over accepted sources, generate + persist
  anchors. `400` if the topic has no accepted sources. Returns
  `{ anchors: [AnchorOut...], events: [EventOut...] }`.
- `GET /api/topics/{topic_id}/anchors` (optional `?concept_id=`) → list anchors (review/nav).
- `GET /api/concepts/{concept_id}/anchors` → anchors for one concept.
- `POST /api/concepts/{concept_id}/assess` — `AssessIn` gains `anchor_id: int | null`; the
  `source_quiz` kind now grades against the anchor and `400`s cleanly if no anchor exists.

### 3.2 Generation flow (`engine/anchors.py`)

```
load accepted SourceDocs for topic ──► 400 if none
load topic key_concepts (foundation) + the track's Concepts
build AnchorBrief per source (title, summary, url, key_concepts)
fan out (ThreadPoolExecutor) ──► per-source list[RawAnchor], collected in source order
for each RawAnchor: link concept by name; dedupe on (source_doc_id, anchor_key(question))
persist ReferenceAnchor rows; emit anchors:plan / anchors:subagent(per source) / anchors:done
commit ; return AnchorGenResult(anchors, events)
```

- **Pure, unit-tested helpers:** `anchor_key` (normalize a question), `match_concept`,
  `dedupe_anchors`, `parse_anchors_json`, `build_anchor_brief`.
- **Observability:** one topic-scoped `AgentEvent` per step (plan, per-source, done).

### 3.3 source_quiz grading (`engine/assess.py`)

Add the `source_quiz` branch described in §2.6 alongside the existing `artifact_review` /
rubric branches. Resolution helper raises `AnchorError` (→ route maps to 400). Everything
downstream (rules layer, `penalize_score`, estimate update, events) is unchanged — the anchor
just supplies a stronger, source-attributed set of gradeable points.

### 3.4 Surfacing

- Review/track UI: a "Generate quizzes from sources" action calling
  `POST /api/topics/{id}/anchors`, with the fan-out trace shown (like research).
- Assess UI: re-enable the **Source quiz** option for concepts where `has_anchor` is true;
  show the anchor's question; grade the typed answer against it.
- `ConceptOut.has_anchor` drives a per-concept "quiz available" indicator.

## 4. Out of scope (later)

Full-text source fetch for anchor grounding; track-wide assessment sweep / heatmap (full C);
multi-probe synthesis (B); user-editable anchors review workflow beyond list/generate;
auto-generating anchors during research; streaming; auth.

## 5. Definition of done

- `POST /api/topics/{id}/anchors` fans out over accepted sources (parallel, one subagent each)
  and persists deduped, concept-linked `ReferenceAnchor`s; `400` with no accepted sources;
  re-running does not duplicate (deterministic unit test).
- `source_quiz` assessment grades against a `ReferenceAnchor` (question/reference/key_points),
  sets `Assessment.anchor_id`, and `400`s cleanly when no anchor exists; the deterministic
  rules layer still fires on omitted key_points.
- Fan-out reuses the Plan 2 mechanism (Protocol client + thread-safe by-source scripted
  double + `ThreadPoolExecutor`), tested without network.
- Navigation: `ConceptOut.has_anchor` exposed; assess UI re-enables source_quiz only where an
  anchor exists; a "Generate quizzes from sources" affordance exists.
- One `AgentEvent` per generation step; pure helpers unit-tested; full loop integration test
  (research → curriculum → generate anchors → source_quiz assess against an anchor → estimate
  updates); no migration; Plans 1–5 paths intact; ruff clean.
