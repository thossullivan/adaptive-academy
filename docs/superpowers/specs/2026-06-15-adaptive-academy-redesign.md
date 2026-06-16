---
title: Adaptive Academy — Greenfield Redesign Spec (v1)
created: 2026-06-15
status: draft — awaiting user review
owner: thossullivan
companions:
  - ../../research/2026-06-15-learning-science-evidence.md   # evidence base (pass 1 + pass 2)
supersedes: the existing adaptive-academy (Python/AutoGen + BAML + placeholder UIs)
---

# Adaptive Academy — Greenfield Redesign Spec (v1)

## 0. One-paragraph summary

A **private, single-user, local-first** adaptive learning system that the author
**dogfoods** for self-directed adult learning. You spin up a **Topic**; a fan-out
**Researcher** gathers and triages foundational sources; a brainstorm-style
**onboarding** shapes intent; a **CurriculumDirector** produces a **phased tracker**
(the same shape as the author's hand-written `llm-from-scratch-tracker.md`). You then
work it **blended** — structured items plus a **generation-first Tutor** you talk to —
while an **Assessor** probes real understanding (self-explanation + artifact review,
not trivia) and a **build-in-public log** doubles as reflection *and* spaced retrieval.
Multi-agent orchestration is **explicit and observable**, with the **Claude Agent SDK
used specifically for fan-out** work. Everything round-trips to/from markdown.

This redesign is **greenfield**: it discards the prior Python/AutoGen + BAML code and
the two placeholder UIs, and is built fresh, mirroring the proven architecture of the
sibling `hybrid-coach` project.

## 1. Goals & non-goals

### Goals
- A tool the author will **actually use** to learn hard technical subjects (first
  topic: *building LLMs from scratch*; see the author's tracker artifacts).
- **Real, observable multi-agent orchestration** — specialized role-agents + an
  explicit orchestrator, with fan-out where it pays off.
- **Pedagogy grounded in evidence** (see companion evidence doc), not vibes — in
  particular, designed to *avoid* the documented failure mode where AI tutoring
  boosts in-session performance but **harms durable learning**.
- **Local-first data** (SQLite on your machine, single user). Calls the **Claude API**
  for intelligence — "local-first" here means data sovereignty, not on-device models.
- **Markdown round-trip** so tracks interoperate with the author's existing note
  workflow and build-in-public writing.

### Non-goals (v1)
- ❌ Multi-user, auth, accounts, sharing (single user; auth deferred — see §9).
- ❌ On-device / offline LLM inference (that constraint belongs to the *separate*
  parent-assistant project, which has child-data reasons; not this tool).
- ❌ Mobile app (responsive web is enough).
- ❌ The Memory/Progress agent and rich spaced-repetition scheduling (v1.5).
- ❌ A content corpus / RAG product surface (the Researcher fetches per-topic; we are
  not building a curated grounding corpus like the parent-assistant).

## 2. The pedagogical spine (why the design is shaped this way)

Grounded in `docs/research/2026-06-15-learning-science-evidence.md`. The five load-
bearing findings and their direct design consequences:

1. **Expertise-reversal effect** (Endres et al. 2025; novices +0.505, experts −0.428).
   High guidance *helps novices but harms experts.* → **The core adaptive variable is
   ASSISTANCE LEVEL keyed to estimated prior knowledge, not "difficulty."** Default to
   **low-assistance, project-first**; fade scaffolds; re-estimate knowledge continuously.
2. **Over-reliance harms durable learning** (Bastani *PNAS* 2025; pooled RCTs N=1,222;
   Barcaui d=0.68 at 45 days). Unrestricted AI = a crutch that tanks unassisted
   performance, *worst for technical topics.* → **Generation-first Tutor**: withhold
   full solutions, require a logged attempt/explanation before hints, **optimize for
   unassisted, delayed performance.**
3. **Illusion of competence** (IOED; Chromik probe collapses perceived understanding
   for 63–72%; AI explanations inflate confidence). → **Assessor never trusts
   self-reported confidence**; it uses **self-explanation probes + calibration checks**
   (predict → probe → surface the gap) and **delayed/surprise retention**.
4. **Self-explanation (g=0.55) & learning-by-teaching** are validated for learners with
   prior knowledge (author qualifies). → **Artifact-first assessment**; a **shippable
   teaching artifact per phase**; the **build-in-public log is the highest-leverage
   feature.**
5. **Spacing/retrieval are top-tier broadly but attenuate for experts/deep transfer**
   (authentic STEM ~2%); **deliberate practice is over-claimed** (~4% variance in
   education). → Retention is a **first-class, curated layer** (Anki-style spaced
   repetition + active recall), but **curated and concept-targeted** at load-bearing
   ideas — never rote trivia or hour-counting; **authentic artifacts** still carry the
   most weight. (See §2.2.)

> **Design north star:** optimize for **unassisted, delayed understanding**, measured
> by what you can *explain and build without help* — never for in-session fluency.

### 2.1 The tool's stance: a tutor, not a distiller

The AI's value is **not** to read the papers for you and hand back a tidy summary — that
is exactly the **cognitive offloading** the evidence (§8.3) shows degrades durable
learning. Its value is to act as a **tutor** that:

- **Serves and curates pedagogical sources** — finds the foundational papers, generates
  **quizzes/probes *from* those papers**, and points you *into* the material rather than
  around it. The cognitive work of reading, explaining, and building stays with you.
- **Calibrates challenge to just beyond your current depth** — Vygotsky's Zone of
  Proximal Development / Bjork's *desirable difficulties*: keep tasks at the edge of
  your competence, hard enough to push growth, not so hard they collapse. This is a
  **second adaptive lever — "challenge level" — distinct from "assistance level"**
  (§2.3).

> **Anti-goal:** the tool must never let you *feel* you've learned because the AI
> explained it well. Understanding is demonstrated by *you* generating it (explain,
> recall, build), measured against an anchor (§2.4).

### 2.2 Retention layer (curated SRS + active recall)

- **Curated spaced repetition:** the Assessor generates **high-quality cards from the
  actual sources and your demonstrated gaps** (not auto-trivia), surfaced for your
  review/edit before they enter rotation. Scheduled with a standard SM-2-style interval
  algorithm. Cards target **load-bearing concepts** (e.g., `softmax(QKᵀ/√d)V`, why
  softmax subtracts the max, LoRA = low-rank `ΔW = BA`).
- **Active recall (Feynman):** free-recall and self-explanation prompts ("without
  looking, derive/explain X") — the *generative* complement to recognition-style cards.
  These double as retrieval practice and feed the KnowledgeEstimate.
- Evidence guardrail: this layer is **deliberately thin relative to artifact work** for
  an expert pursuing transfer (§5 of the evidence doc), but it is *curated and present*,
  not absent.

### 2.3 Two adaptive levers (keep them distinct)

| Lever | Driven by | Direction for this expert user |
|---|---|---|
| **Assistance level** (how much help the Tutor surfaces) | KnowledgeEstimate (expertise-reversal) | default **low**, fade further as mastery grows |
| **Challenge level** (how hard the next task/probe is) | KnowledgeEstimate + recent performance (ZPD) | target the **edge of competence** — raise on success, lower on struggle |

High prior knowledge ⇒ *less* assistance **and** *higher* challenge. They move together
for an expert but are computed and logged separately.

### 2.4 Assessment needs an anchor (no scoring in a vacuum)

Open-ended understanding **cannot be scored "absolutely"** by an LLM judging in a vacuum
(unreliable; see the 32%-bad-output rate, §8.1). Every assessment must measure against
**something**:

- **Rubric / rules-engine:** each assessable concept/objective carries an explicit
  **rubric** (criteria + what a strong vs. weak answer contains), **derived from the
  source material and user-reviewable**. The LLM grades *against the rubric*, not from
  thin air. Deterministic checks (e.g., does a derivation reach the right expression?)
  go through a **rules layer**, not the LLM.
- **Reference anchor:** quizzes/probes generated **from specific sources** carry a
  **reference answer / key points** from that source — the ground truth to measure
  against.
- **Relative / delta measurement:** where absolute scoring is weak, measure **progress
  relative to your own prior explanation** (re-explain a concept you covered two weeks
  ago; compare) and relative to the source's coverage. **Report deltas, not just
  absolute scores** — this also matches good experimentation hygiene from your own
  tracker.

## 3. Architecture & stack

Mirrors `hybrid-coach` (a proven, well-factored modular monolith).

| Layer | Choice | Notes |
|---|---|---|
| Language (backend) | **Python 3.12**, `uv` | as hybrid-coach |
| API | **FastAPI** | REST; SSE/streaming for chat |
| ORM / DB | **SQLModel** + **SQLite** | local-first, single-user; Alembic migrations |
| LLM | **Anthropic SDK** (async) | model tiers below |
| Fan-out / autonomous work | **Claude Agent SDK (Python)** | Researcher; quiz/probe generation |
| Prompts | **Jinja2 + versioned registry** | as hybrid-coach `prompts/` |
| Frontend | **SvelteKit 2 + Svelte 5 + Tailwind 4** | reuse `ConversationUI`, patterns |
| Frontend↔backend | **REST + SSE**; Vite dev proxy `/api/*` → :8000 | as hybrid-coach |
| Task runner | **just** | mirror hybrid-coach commands |

> **DB choice — deliberate divergence from hybrid-coach.** hybrid-coach uses **Postgres**
> because it is built to be *hosted* (Docker Compose, Caddy, a DB container). This tool is
> **single-user, local-first, and not deployed**, so **SQLite (WAL mode)** is the better
> fit: zero ops, no daemon/container, backup = copy a file. Because the data layer is
> SQLModel, the choice is nearly free to reverse. **Discipline to keep the door open:**
> portable schema (JSON for semi-structured fields — SQLite `json1` ⇄ Postgres `jsonb`),
> no SQLite-only SQL, Alembic **batch mode** for `ALTER TABLE`. Switch to Postgres only if
> this ever becomes hosted/multi-user or needs `pgvector` (and even then, `sqlite-vec`
> covers local embeddings/SRS similarity).

**Model tiers** (current as of 2026-06; revisit via the model registry, not hardcoded):
- **Haiku 4.5** (`claude-haiku-4-5`) — scripted onboarding copy, cheap classification.
- **Sonnet 4.6** (`claude-sonnet-4-6`) — Tutor, CurriculumDirector, Assessor grading,
  Researcher synthesis.
- Escalate specific reasoning-heavy steps to a higher tier behind a config flag if eval
  shows a need; do not hardcode model ids in agents — resolve through a registry.

**Architectural boundaries** (enforce with import-linter, as hybrid-coach):
`models → engine → agents → api`. Agents never import api; models import nothing upward.

## 4. Agents & contracts

Multi-agent orchestration is **explicit**: an Orchestrator owns session state and the
**assistance level**, and routes to role-agents. Most agents are **structured Anthropic
SDK calls**; fan-out agents use the **Claude Agent SDK**.

### 4.1 Orchestrator (always on)
- **Job:** route user intent → the right agent; own the session, the **KnowledgeEstimate**,
  and the derived **assistance + challenge levels** (§2.3); persist conversation state.
- **In:** user message / event + session context. **Out:** routed action + updated state.
- **Key rule:** computes **`assistance_level`** (expertise-reversal; default **low** for
  this expert user) **and `challenge_level`** (ZPD; target the edge of competence) from
  the KnowledgeEstimate, and passes both to every agent. These are the two adaptive
  levers — kept distinct (§2.3).
- Built on hybrid-coach's **tool-tiered conversation engine** (auto vs confirm tools).

### 4.2 Researcher (fan-out — Claude Agent SDK)
- **Job:** given a Topic, **spawn parallel subagents** to gather, triage, and summarize
  **foundational sources** → a **Topic Foundation** (key concepts, prerequisite map) +
  a curated, tiered **reading list** (`SourceDoc`s).
- **In:** topic + brainstorm intent. **Out:** `TopicFoundation` + `SourceDoc[]`.
- **Tools:** web search + fetch (Agent SDK). Dedup by URL; rank by relevance/authority.
- **Confirm-tier:** the proposed reading list is surfaced for the user to accept/prune
  before it seeds the curriculum (keeps the human in the loop; cheap insurance against
  the 32%-bad-output rate seen for unreviewed AI in the evidence).

### 4.3 CurriculumDirector
- **Job:** turn `TopicFoundation` + brainstorm + `KnowledgeEstimate` into an editable
  **phased Track** (phases → items → ship deliverable + sidebars).
- **In:** foundation, intent, knowledge estimate, time budget (e.g., ~10 hrs/wk).
- **Out:** `Track` (markdown-exportable).
- **Evidence-driven rules:**
  - Default **low-assistance, project/problem-first** items (expertise-reversal).
  - **One shippable teaching artifact ("🎯 Ship") per phase** (learning-by-teaching).
  - **Spaced revisits** of load-bearing prerequisites across phases (not massed; not
    everything — only the concepts the Assessor flags as foundational).
  - Treats deliberate-practice drills as *supporting*, not the spine.
- **Adapt mode:** re-sequence / inject a remediation item when the Assessor surfaces a
  gap; keyed on **prior-knowledge**, not raw quiz difficulty.

### 4.4 Tutor (generation-first — the day-to-day surface)
- **Job:** interactive teaching dialogue via the tool-tiered conversation engine.
- **Protocol (the core safety design; from evidence §8):**
  1. **Withhold full solutions by default.** When the user asks "what's the answer,"
     respond with a **hint / Socratic prompt**, not the solution.
  2. **Attempt-gate:** substantive hints require a **logged attempt or explanation**
     first. (Mechanism that "essentially eradicated" learning harm in the Bastani RCT.)
  3. **Scaffold in tiers:** nudge → conceptual hint → worked sub-step → (last resort,
     explicitly flagged) full explanation. Each escalation is logged.
  4. **Fade** assistance as the KnowledgeEstimate rises; periodically force unassisted
     retrieval ("before I help — explain what you think happens here").
  5. **No unwarranted confidence.** The Tutor flags uncertainty rather than asserting
     (AI-expressed confidence miscalibrates user trust).
  6. **Serve sources, don't distill them (§2.1).** Prefer pointing into the actual
     paper/section and posing a probe over hand-summarizing. When it does explain, it
     does so to *unblock*, then hands the generative step back to the user.
  7. **Calibrate challenge to the ZPD (§2.3).** Pick the next task/question at the edge
     of competence — raise difficulty on success, lower on genuine struggle — using the
     `challenge_level` lever, separately from `assistance_level`.
- **In:** message, current item/concept, **assistance level + challenge level**, source
  context. **Out:** reply + tool calls (e.g., `log_attempt`, `propose_srs_card`,
  `propose_recall_prompt`, `flag_gap`, `set_challenge`).
- **Anti-goal:** never optimize for in-session "that was easy," and never let the user
  *offload the cognitive process* — that's the vanity metric and the failure mode the
  evidence warns against.

### 4.5 Assessor (illusion-of-competence detector)
- **Job:** measure *real* understanding and feed adaptation. **Primary** = generative;
  **secondary** = curated retention. **All scoring is anchored (§2.4) — never absolute
  in a vacuum.**
- **Probes (primary):**
  - **Self-explanation probe:** "explain *why* X / *how* Y works." Grade **against an
    explicit rubric** (criteria derived from the source + learning objectives) and the
    Topic Foundation; surface specific gaps. Deterministic sub-checks (a derivation
    reaches the right expression, a definition includes required elements) go through a
    **rules layer**, not the LLM.
  - **Artifact review:** review the phase shippable (blog draft, repo, ablation) against
    its **acceptance-criteria rubric** for understanding gaps, not just surface
    correctness.
  - **Calibration check:** elicit a **confidence prediction → probe → surface the gap**
    (the IOED-collapsing move). Never accept self-reported confidence as truth.
  - **Quizzes from sources:** generate questions **from specific `SourceDoc`s** with a
    **reference answer / key points** attached, so there's ground truth to grade against.
- **Anchoring & relativism (§2.4):** every `Assessment` records what it was measured
  against — a `rubric_id`, a `reference_anchor`, and/or a prior baseline — and reports a
  **delta vs. the user's own prior explanation** where absolute scoring is weak.
- **Retention layer (curated, §2.2):** proposes **curated SRS cards** (from sources +
  demonstrated gaps, user-reviewable) and **active-recall/Feynman prompts**; schedules
  them (SM-2-style). Targets **load-bearing concepts**; supplementary weight relative to
  artifacts.
- **Delayed/surprise** retention + transfer items where feasible (in-session scores are
  inflated; delayed unassisted scores are the real measure).
- **Out:** `Assessment` (verdict + gaps + anchor + delta + concept refs) → updates
  `KnowledgeEstimate` (→ assistance **and** challenge levels), may trigger
  CurriculumDirector adapt + schedule `SRSCard`/`RecallPrompt`s.
- **Fan-out (Agent SDK):** generate probe/quiz variants and candidate SRS cards across
  objectives in parallel; the user curates before they enter rotation.

### 4.6 Memory/Progress — **v1.5 (deferred)**
- Extracts durable facts about the learner (patterns, recurring gaps, preferences) to
  sharpen adaptation over time — like hybrid-coach's `CoachingMemory`. Out of v1 scope.

## 5. Data model (SQLModel / SQLite)

```
Topic 1─* Track 1─* Phase 1─* Item
                     Phase 1─* Deliverable          # the "🎯 Ship"
                     Track/Phase 1─* Sidebar        # math-refresh, reading list, hardware
Topic 1─* SourceDoc                                 # Researcher output (tiered)
Concept 1─1 Rubric                                  # criteria to grade against (§2.4)
SourceDoc 1─* ReferenceAnchor                       # reference answer / key points
Topic/Concept 1─1 KnowledgeEstimate                 # drives assistance + challenge level
Item/Concept 1─* Assessment                         # probe + response + verdict + anchor + delta
Concept 1─* SRSCard                                 # curated spaced-repetition card (§2.2)
Concept 1─* RecallPrompt                            # active-recall / Feynman prompt (§2.2)
Topic 1─* ReflectionEntry                           # build-in-public log
Topic 1─* ConversationThread 1─* Message            # reuse hybrid-coach shape
```

Key entities:
- **Topic** — a subject the user is learning (e.g., "Build LLMs from scratch").
- **Track** — a Topic's current plan (a Topic may re-plan; keep history).
- **Phase** — ordered; `est_hours`, flags: `optional | stretch | parallel_track`.
- **Item** — `type ∈ {read, watch, build, write}`; `status ∈ {todo, doing, done}`;
  `links[]`; optional `source_doc_id`; optional `concept_refs[]`.
- **Deliverable** — `type` (blog/repo/model/talk/ablation), `acceptance_criteria`,
  `artifact_url`, `review_verdict`.
- **Sidebar** — `kind ∈ {math_refresh, reading_list, reference}`, `body` (markdown).
- **SourceDoc** — `title, url, tier ∈ {1,2,3}, summary, why, added_by='researcher'`.
- **KnowledgeEstimate** — per Topic/concept: `level`, `confidence`, `last_assessed_at`,
  `evidence` (which assessments informed it). Drives **`assistance_level`** *and*
  **`challenge_level`** (§2.3).
- **Rubric** — per concept/objective: `criteria[]`, `strong_answer_contains[]`,
  `weak_answer_signs[]`, `source_refs[]`, `reviewed_by_user: bool`. The anchor the
  Assessor grades against (§2.4).
- **ReferenceAnchor** — per source-derived question: `source_doc_id`, `question`,
  `reference_answer`, `key_points[]`. Ground truth for "quizzes from sources."
- **Assessment** — `kind ∈ {self_explanation, artifact_review, calibration,
  source_quiz, recall}`, `prompt`, `response`, `verdict`, `gaps[]`,
  `confidence_predicted`, `confidence_actual`, **`rubric_id?`, `anchor_id?`,
  `baseline_assessment_id?`, `delta`** (progress vs. prior baseline, §2.4).
- **SRSCard** — `concept_id`, `front`, `back`, `source_ref?`, `curated_by_user: bool`,
  `interval`, `ease`, `due_at`, `last_result` (SM-2-style; §2.2).
- **RecallPrompt** — `concept_id`, `prompt`, `due_at`, `last_result` — generative
  free-recall / Feynman complement to `SRSCard` (recognition).
- **ReflectionEntry** — `kind ∈ {decision, self_explanation, free_recall, milestone}`,
  `body`, `is_public`, `prompt` (if model-elicited), `phase_id?`.
- **ConversationThread / Message** — mode (`tutor | onboarding | curriculum`), roles,
  tool_calls, token_count, `client_request_id` (idempotency) — reuse hybrid-coach.

Markdown round-trip: a `Track` ⇄ a tracker markdown doc (phases as `##`, items as
checklist lines, "🎯 Ship" deliverables, sidebars as labeled sections) — matching the
author's existing `llm-from-scratch-tracker.md` format.

## 6. Key flows

### 6.1 New Topic (onboarding + research)
1. **Brainstorm onboarding** (hybrid-coach pattern: hardcoded step sequence, Haiku
   generates warm copy, structured inputs): goal, prior knowledge, time budget,
   constraints, what "done" looks like.
2. **Researcher fan-out** → `TopicFoundation` + tiered `SourceDoc` reading list.
3. **User reviews/prunes** the reading list (confirm-tier).
4. **CurriculumDirector** → editable **Track** (phased tracker). User can edit and
   export to markdown.

### 6.2 Work a phase (blended)
- Structured items (read/watch/build/write) + **Tutor** chat (generation-first,
  low-assistance) in the same view. Check off items; the Tutor logs attempts and flags
  gaps as you go.

### 6.3 Assess
- At item/phase boundaries (or on demand), the **Assessor** runs a self-explanation
  probe / calibration check / artifact review → writes an `Assessment`, updates the
  `KnowledgeEstimate`, and surfaces gaps.

### 6.4 Adapt
- The **Orchestrator** recomputes **`assistance_level` and `challenge_level`**; the
  **CurriculumDirector** may re-sequence or inject a remediation item; the **Assessor**
  schedules curated **`SRSCard`s / `RecallPrompt`s** on weak load-bearing concepts. All
  keyed on prior knowledge (§2.3).

### 6.5 Reflect / build-in-public
- A journal view; entries are **self-explanations of decisions** and **milestone**
  posts (per-phase shippable). The system periodically issues **delayed free-recall
  prompts** ("without looking, explain X from two weeks ago") — turning the log into
  retrieval practice. Entries can be marked public for later export.

## 7. UI surface (SvelteKit, reuse `ConversationUI`)

- **Topics dashboard** — your topics + progress.
- **Track / tracker view** — phases, items (checkable), progress, "🎯 Ship"
  deliverables, sidebars; markdown export button.
- **Tutor chat** — generation-first dialogue; visible "attempt-first" affordance; a
  subtle **assistance-level indicator** (so fading is legible, not mysterious).
- **Assessor view** — probe / calibration / artifact-review interactions; shows the
  **rubric it graded against** and the **confidence-vs-actual gap** and **delta vs. your
  prior baseline**.
- **Review / retention** — due **SRS cards** + **active-recall prompts** (a daily-review
  surface); each card shows its source and is user-editable before entering rotation.
- **Build-in-public log** — journal; free-recall prompts; public toggle.
- **Source library** — the Researcher's tiered reading list per topic.

Styling: Tailwind, minimal and calm. Reuse hybrid-coach's component conventions.

## 8. Repo structure (new repo, same remote optional)

Greenfield top-level (mirrors hybrid-coach):

```
adaptive-academy/                 # fresh git history; may point at existing remote
├── src/adaptive_academy/
│   ├── api/                       # FastAPI: topics, onboarding, tracks, tutor, assess, reflect
│   ├── agents/                    # orchestrator, researcher, curriculum, tutor, assessor
│   ├── engine/                    # tool-tiered conversation loop, assistance-level logic
│   ├── prompts/                   # versioned Jinja2 registry
│   ├── models.py                  # SQLModel tables
│   ├── db.py  settings.py  cli.py
├── frontend/                      # SvelteKit (reuse ConversationUI, patterns)
├── docs/
│   ├── research/                  # evidence base (carried over)
│   └── superpowers/specs/         # this spec
├── alembic/  tests/  justfile  pyproject.toml
```

**Setup decision (for the impl plan):** new local directory with fresh history; either
(a) repoint at the existing `adaptive-academy` GitHub remote via a clean orphan branch /
replace `main`, or (b) a brand-new remote. The old code is preserved in git history
either way. Archive the prior `main` as a `legacy/` tag before replacing.

## 9. Cross-cutting concerns

- **Auth:** none in v1 (single user, localhost). Keep hybrid-coach's magic-link pattern
  available behind a flag if the tool is ever exposed beyond localhost. **Do not** add
  it to v1 scope.
- **LLM robustness:** async client with retries/timeouts (hybrid-coach tiers: ~60s
  conversation, ~120s generation); structured outputs validated with Pydantic; fallback
  copy on failure (onboarding).
- **Observability:** log every agent action + assistance-level decision; the multi-agent
  flow must be inspectable (a "what did the agents do" trace), serving the "observable
  orchestration" goal.
- **Cost:** Haiku for scripted copy; fan-out is the main cost driver — cap Researcher
  subagents and log what was dropped.
- **Privacy:** local SQLite; only prompts/sources go to the Claude API; no telemetry.

## 10. Testing & evaluation

- **Unit:** models, assistance-level computation, markdown round-trip (Track ⇄ md).
- **Integration:** onboarding → research → track generation (mock LLM); assess → adapt.
- **Prompt/agent evals (promptfoo-style):** golden cases for the Tutor's **attempt-gate**
  (does it withhold solutions until an attempt is logged?), the Tutor's **no-distillation
  stance** (does it point into sources + pose a probe rather than hand back a summary?),
  and the Assessor's **calibration probe** (does it surface confidence-vs-actual gaps?).
  **Rubric-anchored grading** is tested against gold rubrics so judge variance is bounded
  (no scoring in a vacuum). These encode the evidence-based guardrails as **regression
  tests** — a regression on "Tutor reveals answer without an attempt" is a release
  blocker, mirroring how the parent-assistant treats safety regressions.
- **Dogfize loop:** the author using it on the real LLM-from-scratch topic is the
  primary acceptance test.

## 11. v1 scope vs. deferred

**v1:** Topic onboarding + Researcher (fan-out); Track generation + tracker UI + md
round-trip; blended Tutor (generation-first, attempt-gate, fading, **ZPD challenge
calibration**); Assessor (self-explanation + artifact review + calibration + **quizzes
from sources**, all **rubric/anchor-grounded with delta scoring**); **curated retention
layer** (SRS cards + active-recall/Feynman prompts, SM-2-style scheduling); build-in-
public log; observable orchestration trace.

**v1.5+:** Memory/Progress agent; **advanced SRS scheduling/optimization** (beyond
SM-2); multi-topic interleaving; one-click public publishing of the log; optional auth
if exposed.

## 12. Open questions / risks

1. **No durable-gain evidence yet** for *well-designed* generation-first tutors (the
   guardrail only *neutralized* harm in the one field RCT). Mitigation: pair
   answer-withholding with forced generative effort (retrieval, self-explanation,
   shippables) — but treat efficacy as a hypothesis we test by dogfooding, and keep the
   assessment honest (delayed/unassisted).
2. **Population transfer:** evidence is K-12/undergrad; the author is an advanced adult.
   Directions transfer; magnitudes/thresholds (e.g., how hard to gate hints) need tuning
   from real use.
3. **Fan-out cost/quality:** Researcher can be expensive and can surface low-quality
   sources (32% bad-output rate seen for unreviewed AI). Mitigation: user-reviewed,
   tiered reading list; caps + logging.
4. **Repo/remote setup** (§8) — confirm during the implementation plan.
5. **Assistance-level estimation** is the linchpin and the hardest unknown — how to
   estimate prior knowledge cheaply and keep it current without nagging. Start simple
   (seed from onboarding + update from Assessments) and iterate.

## 13. What we are explicitly NOT reusing from the old repo

- AutoGen agents, BAML, the OpenAI client path, the two placeholder UIs
  (`dashboard/`, `frontend/`), and the old FastAPI surface. Prompt *content* and the
  SQLite *schema ideas* may be mined as reference, nothing more.
