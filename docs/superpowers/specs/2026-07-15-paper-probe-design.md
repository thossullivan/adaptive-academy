---
title: Paper Probe — critical paper-reading probes (research-apprenticeship slice 1)
created: 2026-07-15
status: approved for planning
companion_to:
  - 2026-07-09-program-layer.md
  - 2026-07-15-roleplay-examiner-design.md
  - ../../research/2026-06-15-learning-science-evidence.md
---

# Paper Probe — Critical Paper-Reading Probes

**Status:** Approved for planning.

## Goal

Add a **Paper Probe**: read a real paper, then get **adversarially probed** on its
method, load-bearing assumptions, threats to validity, connection to your own work, and
what you'd change — a **structured, generation-first question set** that is **blind-graded
per load-bearing concept** so each probe produces gate evidence on a milestone. It works
identically for technical and non-technical Programs; the paper and the concepts are the
only difference.

This is the first of two slices of the deferred **research apprenticeship** the Program
Layer spec names as "the capstone's machinery." This slice ships **paper ingestion +
critical-reading probe**. The heavier **reproduce-then-extend** deliverable is a separate
follow-up spec (§ Non-goals) — and the probe's *"what would you extend"* answer is its
designed on-ramp.

## Why

The evidence base defines "research-ready" as *verified depth on real literature*: can you
dissect a primary source — not recite it, but interrogate its method and hold up its
weaknesses — and connect it to what you're building? Adaptive Academy has generation-first
tutoring, teach-back, productive failure, and adversarial roleplay, but the
**critical-reading-of-real-literature** slice of deliberate practice has no home. Roleplay
exercises social/adversarial defense (a skeptical buyer, a thesis committee); the Paper
Probe exercises the *epistemic* skill roleplay doesn't — disciplined dissection of one real
artifact. The market's paper-reading tools are passive summarizers; a BYOK, generation-first
probe wired into a personal learning map is genuinely differentiated.

## Scope

**In:** paper ingestion (arXiv HTML via the existing SSRF-guarded fetch, plus a universal
paste fallback); a scenario director that generates a structured critical-reading question
set from the paper + the milestone's load-bearing concepts; generation-first answers; a
blind per-concept grader writing `Assessment(kind="paper_probe")` rows; API; UI; migration;
tests.

**Out (deferred):** reproduce-then-extend deliverable (own spec); PDF parsing; a paper
library / cross-probe dedup; the multi-turn examiner-dialogue variant (that is roleplay
pointed at a paper — build it there if wanted); citation/bibliography graphs;
learner-authored question sets.

## Architecture

Chosen approach: **mirror the roleplay engine, with dedicated leaf tables.** The Paper Probe
reuses the substantial plumbing — the 3-backend `LLMClient.complete` loop, `AgentEvent`
tracing, and `assess.py`'s anchored/anti-sycophancy grading — but stores its state in its
**own leaf tables** so nothing in the tutor's or roleplay's paths is destabilized. Because
the director and outcome calls use **no tools**, a single code path works across
**anthropic, agent_sdk, and scripted** — no `_sdk` variant.

```
Paper Probe (started milestone)
      │  paper_url (arXiv) | pasted_text
      ▼
[0] Ingest  ── engine/paper.py ──►  PaperExtract{title, text, source}     status: drafting
      │         arXiv URL → html endpoint via SSRF-guarded fetch; else paste
      ▼
[1] Director ── PAPER_PROBE_DIRECTOR ──►  question set (JSON)              status: drafting→answering
      │          reads paper_text + milestone load-bearing concepts (+estimates)
      │          each Q tagged {axis, concept_ids}
      ▼
[2] Answer  ── PaperProbeAnswer per Q ──►  generation-first, no feedback   status: answering
      ▼
[3] Submit  ── user submits ──►                                           status: answering→(grade)
      ▼
[4] Blind grade ── assess_concept(kind="paper_probe") per concept ──►     status: →graded
         + PAPER_PROBE_OUTCOME narrative        Assessment rows → gate artifact axis
```

**The three-part anti-sycophancy guard** (carried over from roleplay): (1) question
difficulty is *pinned to current concept estimates* via `compute_levels` (expertise-reversal:
don't grill a novice on frontier nuance, don't coddle an expert); (2) grading is a *separate
blind pass* under `assess.py`'s deterministic omission/misconception/no-mechanism ceilings,
which cannot be charmed; (3) the learner answers **before** any feedback exists —
generation-first is enforced by ordering (no grade exists until submit), not by prompt text.

**Seam to the capstone:** the *"what would you extend"* question. Its answer is a natural
seed for the reproduce-then-extend deliverable — that follow-up spec can read the most recent
probe's extension answer as its starting proposal without any rework here.

## Components

| Unit | Responsibility | Depends on |
|------|----------------|-----------|
| `PaperProbe` / `PaperProbeAnswer` (models) | Session state + paper + answers | `Program`, `Milestone` |
| `engine/paper.py::ingest_paper` | URL/paste → `PaperExtract{title, text, source}` | `fetch.py` (guarded fetch), stdlib `html.parser` |
| `engine/paper_probe.py::direct` | Generate question set from paper + load-bearing concepts | LLM registry, `gates.milestone_load_bearing`, `compute_levels`, `PAPER_PROBE_DIRECTOR` |
| `engine/paper_probe.py::grade_paper_probe` | Blind per-concept grading → `Assessment` rows + outcome | `assess.assess_concept`, `PAPER_PROBE_OUTCOME` |
| `api/routes_paper_probe.py` | REST surface | the engine, `deps` |
| prompts (`PAPER_PROBE_DIRECTOR`, `PAPER_PROBE_OUTCOME`) | Version-tagged prompt text | `prompts.py` registry |
| Frontend `/paper-probe/[id]` + milestone "Probe a paper" entry | Answer UI + scorecard | roleplay scorecard component, UI kit |

## Data Model

Two new leaf tables (created fresh — no ALTER of existing tables) and two additive nullable
columns.

**`PaperProbe`**
- `id: int (pk)`
- `program_id: int (fk program.id)`
- `milestone_id: int (fk milestone.id)`
- `paper_title: str`
- `paper_url: str = ""` (empty for pasted papers)
- `paper_text: str` — extracted or pasted, char-capped (see Ingestion)
- `source: str` — `"arxiv" | "paste"`
- `status: str` — `"drafting" | "answering" | "graded"`
- `questions: JSON` — `[{index: int, axis: str, prompt: str, concept_ids: [int]}]`
- `outcome: JSON | null` — `{result: str, summary: str}` (set at grade time)
- `created_at`, `updated_at: datetime`

**`PaperProbeAnswer`**
- `id: int (pk)`
- `probe_id: int (fk paperprobe.id)`
- `question_index: int`
- `content: str`
- `created_at: datetime`

**Additive columns (plain `op.add_column`, nullable — never `batch_alter_table`, which
rebuilds the table and breaks FKs on real data):**
- `Assessment.paper_probe_id: int | null (fk paperprobe.id)` — traces each piece of gate
  evidence back to its probe. `Assessment.kind` gains the value `"paper_probe"` (no schema
  change — `kind` is free text).
- `AgentEvent.paper_probe_id: int | null (fk paperprobe.id)` — observability trace, mirroring
  the existing `program_id` / `conversation_id` / `roleplay_session_id` links.

**Paper storage:** the extracted paper text lives **on the `PaperProbe` row** (as
roleplay's `persona_brief` lives on its session). No separate `Paper`/library table and no
cross-probe dedup in v1 — a program-level paper library is a clean later add if re-probing
the same paper becomes common.

**Availability rule:** a milestone can be probed only once its topic is materialized and has
load-bearing concepts (via the existing lazy-start), so the grader has concepts to credit.
Before that, "Probe a paper" returns 400 with a "start the topic first" message. Identical to
the roleplay availability rule.

**Public vs. hidden:** the API exposes the paper meta + question `prompt`s + `axis` to the
client. The per-question `concept_ids` mapping and all grading internals are withheld until
after grading (so the learner answers the question, not the rubric), then surfaced in the
scorecard.

## Ingestion (`engine/paper.py`)

`ingest_paper(*, url: str | None = None, pasted_text: str | None = None, title: str | None = None) -> PaperExtract`
where `PaperExtract` is a dataclass `{title: str, text: str, source: str}`.

- **arXiv URL** — accept `abs`, `pdf`, or `html` forms; extract the arXiv id; normalize to
  `https://arxiv.org/html/{id}` (latest version). Fetch through the **existing SSRF-guarded
  path** in `fetch.py` (already https-only, `arxiv.org`-suffix-allowlisted,
  public-IP-checked) — parameterized with a **higher byte cap** for this deliberate
  single-document pull (the default 200 KB truncates full papers mid-document). Strip HTML to
  text with a **stdlib `html.parser`-based** stripper (no new dependency). Title from the
  page `<h1>` (fallback `<title>`), overridable by the caller's `title`. `source="arxiv"`.
- **Pasted text** — stored directly with the caller's `title` (fallback: first non-empty
  line). Universal fallback for non-arXiv papers or older papers with no HTML version.
  `source="paste"`.
- **Neither / non-arXiv URL without paste** — raise a legible error → 400 at the route ("give
  an arXiv URL or paste the paper text").
- **Extracted text is char-capped** (~60 k chars — enough to carry intro/method/results into
  the director prompt) to keep grounding prompts sane. Both caps (fetch bytes, extracted
  chars) are tunable constants in `paper.py`.

The byte cap is parameterized on the guarded fetch (a new keyword with the existing 200 KB as
default) rather than raised globally — the artifact-review path keeps its tight cap; only the
paper path opts into the larger one.

## Data Flow (per stage)

1. **Create + ingest + direct.** `POST …/paper-probe` → availability check → `ingest_paper`
   → create `PaperProbe(status="drafting")` → `direct()` runs `PAPER_PROBE_DIRECTOR` over
   `paper_text` + load-bearing concept names/estimates (via `compute_levels`) → a
   **5–7-question** set, each tagged with an `axis` (method / load-bearing-assumption /
   threat-to-validity / connection-to-your-work / what-you'd-extend) and the `concept_ids` it
   exercises → `status="answering"`; return the **public** probe (paper meta + question
   prompts + axes).
2. **Answer.** `POST /api/paper-probe/{id}/answers` `{question_index, content}` → persist
   `PaperProbeAnswer`. No feedback returned (generation-first). Re-answering a question
   updates that answer.
3. **Submit + grade.** `POST /api/paper-probe/{id}/submit` → `grade_paper_probe()`: for each
   load-bearing concept, gather the answers whose questions map to it (via `concept_ids`),
   join their text, call the **existing** `assess_concept(session, concept, "paper_probe",
   combined_text, llm=llm)` (LLM band under deterministic omission/misconception/no-mechanism
   ceilings) → write one `Assessment(kind="paper_probe", paper_probe_id=…)` per concept
   (score, gaps, verdict); run one `PAPER_PROBE_OUTCOME` call for the narrative → write
   `outcome`; `status="graded"`. **Idempotent re-grade:** delete prior `paper_probe`
   assessments for this probe first (roleplay's pattern). Evidence is picked up by gates
   automatically (they already read `Assessment`).

Concepts the paper does not exercise receive no evidence from this probe — that is expected;
use another paper.

## Gate mapping

`ARTIFACT_KINDS` in `engine/gates.py` gains `"paper_probe"`. A graded probe with score ≥
`ARTIFACT_THRESHOLD` (0.7) satisfies a concept's **artifact_ok** axis. It does **not**
substitute for delayed recall: a concept still needs its ≥7-day cold `recall` to satisfy
`delayed_ok` and fully pass the gate. Identical to the roleplay gate decision — preserving
the anti-illusion spaced-recall guard while letting a probe move the artifact axis.

## API (`api/routes_paper_probe.py`)

- `POST /api/programs/{pid}/milestones/{mid}/paper-probe` `{url?, pasted_text?, title?}` →
  `{probe_id, status, paper: {title, url, source}, questions: [{index, axis, prompt}]}`;
  400 if no materialized load-bearing concepts or if neither `url` nor `pasted_text` given;
  404 on program/milestone mismatch.
- `POST /api/paper-probe/{id}/answers` `{question_index, content}` → `{status}`; 400 unless
  `status=="answering"`.
- `POST /api/paper-probe/{id}/submit` → `{status:"graded", outcome, scorecard:[{concept_id,
  concept, score, verdict, gaps}]}`; idempotent (re-submit re-grades).
- `GET /api/paper-probe/{id}` → `{status, paper, questions, answers, outcome|null,
  scorecard|null}`.
- `GET /api/programs/{pid}/milestones/{mid}/paper-probe` → past probes `[{id, paper_title,
  created_at, status}]`.

Backend selection follows existing `deps` (`get_llm`); no probe-specific branching (no tools).

## UI

- **Entry:** a **"Probe a paper"** action on the milestone (program detail), beside "Spar",
  enabled only when the topic is materialized. Disabled state links to "start the topic."
  Input: an arXiv URL **or** a paste box (+ optional title).
- **Probe page `/paper-probe/[id]`:** paper title/header (public brief); the question list,
  each with its `axis` label and an answer box; a single **"Submit for grading"** at the
  bottom — no per-answer feedback (generation-first).
- **After grading:** an outcome banner + a **per-concept scorecard** (score as
  `Math.round(score*100)%`, plain-text verdict, gaps, "what to drill") with a link back to
  the milestone gate so the probe visibly moves the artifact axis. Reuses the roleplay
  scorecard component's corrected rendering (plain text, not a pill).
- **History:** past probes listed on the milestone with paper titles + status.

## Error Handling

- Ingestion failure (fetch returns nothing, non-arXiv URL with no paste, unparseable) →
  legible 400 at the route before any `PaperProbe` row is created; on director failure the
  session is left `drafting` (discardable / re-runnable), never dangling in `answering`.
- Director / outcome LLM failures ride the existing `anthropic.APIError → 502` /
  `AgentSDKError → 502` handlers. No new global handlers.
- A failed grade leaves `status="answering"` (answers preserved, re-gradable) — never lost.
- Submit with unanswered questions is allowed; only-answered questions contribute evidence
  (partial submit grades what exists).

## Testing (TDD, scripted backend — zero live API)

Add scripted director/outcome fixtures and an injected `fetch` double so the whole flow is
deterministic. Cases:

1. **Ingestion:** arXiv `abs`/`pdf` URL → normalized `https://arxiv.org/html/{id}` (injected
   fetch double asserts the URL); HTML→text stripping drops tags; paste passthrough preserves
   text + title; non-arXiv URL with no paste → error; extracted text is char-capped.
2. **Director** produces a well-formed question set (5–7 items; each has `axis`, non-empty
   `prompt`, and `concept_ids` drawn from the milestone's load-bearing concepts).
3. **Answer persistence:** answers stored by `question_index`; re-answering updates in place.
4. **Grader** writes **exactly one** `Assessment(kind="paper_probe", paper_probe_id=…)` per
   load-bearing concept, **with the deterministic ceilings applied** (omission/misconception
   caps from `assess.py`).
5. **Gate integration (the end-to-end test the roleplay plan omitted):** a `paper_probe`
   assessment ≥ 0.7 flips a concept's `artifact_ok`; below-threshold does not; a graded probe
   advances a real milestone gate's artifact axis (`milestone_gate` report reflects it).
6. **Availability rule:** milestone with no materialized/load-bearing concepts →
   `POST …/paper-probe` returns 400.
7. **Grade-failure path:** answers preserved, `status="answering"`, re-gradable.
8. **Idempotent re-grade:** a second submit deletes prior `paper_probe` assessments and
   rewrites, not duplicates.

`conftest` retains `PRAGMA foreign_keys=ON` (prod parity). One **additive** Alembic migration
— `create_table` × 2 + `add_column` × 2 (all nullable), **no `batch_alter_table`** —
accompanied by the populated-DB regression test pattern (seed the prior revision with
referencing rows, run the real migration via subprocess alembic, assert success).

## Migration

Single revision (`down_revision` = the roleplay revision `af45456b0fc5`):
- `op.create_table("paperprobe", …)`
- `op.create_table("paperprobeanswer", …)`
- `op.add_column("assessment", sa.Column("paper_probe_id", sa.Integer(), nullable=True))`
  — plain `sa.Integer()` nullable, **not** `sa.ForeignKey` (SQLite/Alembic cannot ADD COLUMN
  with an inline FK outside the forbidden batch mode; the ORM `foreign_key=` on the model
  keeps referential intent, and `create_all` test DBs enforce it). Mirrors the
  `roleplay_session_id` precedent.
- `op.add_column("agentevent", sa.Column("paper_probe_id", sa.Integer(), nullable=True))`

All additive; safe on the populated container DB.

## Non-goals / future

- **Reproduce-then-extend deliverable** (research-apprenticeship slice 2, its own spec) — it
  plugs into Milestones as the capstone artifact and reads this probe's *"what would you
  extend"* answer as its seed proposal.
- **PDF parsing** — arXiv HTML + paste covers v1; add a parser only if a real paper can't be
  reached either way.
- **Paper library / cross-probe dedup** — paper text lives on the probe in v1; promote to a
  program-level table if re-probing the same paper becomes common.
- **Multi-turn examiner dialogue** — that is roleplay pointed at a paper; build it there.
- **Citation/bibliography graphs; learner-authored question sets.**

## Open questions (carried into planning)

- Question count (5–7) and the axis set are starting points to tune from dogfood data.
- The extracted-text char cap (~60 k) and paper-path fetch byte cap are defaults to tune.
- Whether partial-submit grading should warn when < half the questions are answered — decide
  during frontend planning.
