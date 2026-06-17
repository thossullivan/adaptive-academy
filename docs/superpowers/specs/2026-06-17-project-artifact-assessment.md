# Project / Artifact Assessment ("Ingest") — design spec

**Goal:** Make project assessment *real* — grade the actual shipped artifact against the
acceptance criteria the learner committed to, not a self-description of it. Authentic,
artifact-first assessment is the highest-value method for advanced learners (evidence base
§3–§4 + TL;DR), and it's currently the weakest link in the loop.

## Why now / current gaps (confirmed in code)
The bones exist but the wiring is broken in three places:
1. `assess_concept`'s `artifact_review` branch grades the learner's *written self-review*, not
   the work — the illusion-of-competence trap we just closed on the quiz path.
2. The frontend never passes `item_id`, so `_deliverable_criteria()` returns `[]` and the
   grader runs against an **empty** rubric.
3. `Deliverable.artifact_url` / `review_verdict` are written nowhere (0/5 in the DB); there's
   no "I shipped this" affordance, and "shipped" is not a competence signal.

## Decision: build "Ingest" (grade the work), seam left for execution
Rejected "criteria-anchored self-review" (grades the description — gameable, violates our
anti-Goodhart spine). Deferred "sandboxed execution" (correctness checks; its own project —
security + infra). Ingest is the research-and-design sweet spot and *subsumes* self-review.

## Design

### 1. Ship affordance (Track page, per phase deliverable)
A "Ship it" action on the 🎯 Ship card → form: **artifact URL** (repo/blog/notebook) **and/or
pasted content** (code, writeup, ablation table). Sets `Deliverable.artifact_url`; the pasted
content is the review `response`.
- Backend: `PATCH /api/deliverables/{id}` (or fold into the review call) sets `artifact_url`.

### 2. Artifact-anchored review (Assessor)
Grade the **submitted artifact content** against the deliverable's **`acceptance_criteria` as
the rubric anchor** — same pattern as source anchors, same `assess.grade@v3` skeptical
philosophy (criteria = must-*demonstrate*, mechanism cap, band-anchored score).
- Wire `item_id` through the assess route so `_deliverable_criteria()` returns the real
  criteria; the frontend passes the deliverable's item.
- **Ingest:** the response = pasted content + (optional) fetched URL text. Add a best-effort
  fetch of `artifact_url` (httpx, text-only, size-capped, failures degrade to paste-only —
  never block the grade). Demarcate fetched/pasted content as UNTRUSTED (reuse the injection
  delimiters).
- Persist the `artifact_review` Assessment (concept-scoped) AND write `Deliverable.review_verdict`.
- New prompt `assess.artifact` in the registry (skeptical, criteria-anchored, mechanism cap,
  "grade the artifact's design/evidence, not its prose"), version-tagged + traced.

### 3. "Shipped ⚒" becomes the 5th competence signal
In `lib/competence.ts`: derive a `shipped` signal from a passing `artifact_review` assessment
(`kind === 'artifact_review'`, `score ≥ 0.45`) — the hardest-to-game corroborator. Update the
verdict: `solid = grade≥high AND (decay held OR taught OR shipped)`. Add the ⚒ dot to
`SignalStrip` and the Constellation legend stays verdict-based (no change). Pairs with Teach-It
for the full Feynman loop.

### 4. Seam for execution (later, its own project)
The review writes `Deliverable.review_verdict`; a future sandboxed runner becomes **one more
signal** feeding the same verdict — not a rewrite. Out of scope here: no code execution.

## Honest limit
This assesses the artifact's *content and design against criteria*, not "does it run/train/pass
tests." For an advanced learner shipping public artifacts under a teaching expectancy, that
captures most of the authentic-assessment value; execution-correctness is the deferred add-on.

## Files
- `prompts.py` (new `ASSESS_ARTIFACT`), `engine/assess.py` (artifact_review branch ingests +
  writes review_verdict; item_id wired), `api/routes_assess.py` + a deliverable ship route,
  `api/schemas.py`, `models.py` (no schema change — fields already exist).
- Frontend: Track "Ship it" form, Assess `artifact_review` passes item_id + content,
  `lib/competence.ts` + `SignalStrip.svelte` (shipped signal), `lib/api.ts`/`types.ts`.

## Verification
Pure-function + fake-LLM tests for the artifact grade + the `shipped` signal logic; the
fetch path tested with a stub. `pytest` + `ruff` green; frontend `svelte-check` + `vitest` +
build. Merge to main + push.
