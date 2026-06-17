# Four solidification features (research-grounded)

**Goal:** Add four learning-science-backed features that target *durable* learning, grounded in `docs/research/2026-06-15-learning-science-evidence.md`. Each closes a gap the corpus explicitly flags.

## 1. Decay Check — delayed, unassisted retrieval  (§8.2, §8.6, §6)
Corpus: *"Optimize for unassisted, delayed performance, not in-session success."* We only ever assess immediately. Reuses `RecallPrompt` (has `due_at`/`status`) + `Assessment.kind="recall"`.
- `engine/decay.py`: `schedule_decay_check(session, concept_id, days)` (idempotent — one active prompt per concept; updates `due_at`); `due_decay_checks(session, topic_id)`; `grade_decay_check(session, prompt_id, response, *, llm)` → runs `assess_concept(kind="recall")` unassisted, computes **decay** vs the concept's prior best score, reschedules (held → longer interval, decayed → sooner), sets `last_result`.
- Scheduled from the **assess route** after each probe (keeps `engine/assess.py` pristine).
- Routes: `GET /api/topics/{id}/decay`, `POST /api/decay/{prompt_id}/grade`.
- Surfaced in **Retention** page + **Today** warm-up.

## 2. Productive Failure — generate before instruction  (§8.5, §6)
Corpus: withholding answers is *"necessary but not sufficient — must be paired with mechanisms that force generative effort (productive failure)."*
- `engine/productive_failure.py`: `generate_challenge(concept_name, foundation, *, llm)` → a novel application problem with **no method given**; `consolidate(session, concept, problem, attempt, *, llm)` → LLM returns `{canonical, feedback_on_reasoning, score}` grading the **generative struggle**, persists `Assessment(kind="productive_failure")`.
- Routes: `POST /api/concepts/{id}/productive_failure/generate`, `.../consolidate`.
- Frontend: lives in a **Practice** hub. Attempt is gated — you must commit before the canonical is revealed.

## 3. Calibration Loop — predict → explicate → confront  (§8.4)
Corpus: the self-rated-understanding drop is *"the lever the Assessor exploits"*; learners are blind to it.
- Reuses `assess(kind="calibration")`. New: a **calibration accuracy** metric `1 − mean|predicted − actual|` over calibration assessments (computed frontend-side from `listAssessments`), with a trend.
- Frontend (Practice hub): predict confidence **first** → lock → explicate → confront the gap + running calibration accuracy + sparkline. Dashboard gains a calibration-accuracy stat.

## 4. Teach-It — explain to an audience, graded  (§4)
Corpus: build-in-public / learning-by-teaching is the *highest-leverage* feature (protégé effect; explaining + interacting drive durable gains).
- `engine/teach.py`: `grade_teaching(session, concept, explanation, *, llm)` → teaching-expectancy rubric (clarity, correctness, completeness, gaps, strengths), persists `Assessment(kind="teach")`.
- Route: `POST /api/concepts/{id}/teach`.
- Frontend: `/topics/[id]/teach` (Reflect group). A concept shows a **"taught"** badge once a teach assessment exists. Feeds the Progress Story.

## Navigation
Workspace gains **Practice** (`/topics/[id]/practice`, hub for Productive Failure + Calibration). Reflect gains **Teach** (`/topics/[id]/teach`). Decay surfaced in Retention + Today.

## Schema / data
`Assessment.kind` is a free string — `"productive_failure"` and `"teach"` are additive, no migration. `RecallPrompt` reused for decay.

## Verification
Pure-function + fake-LLM unit tests for each engine module; `pytest` + `ruff` green. Frontend `svelte-check` clean, `npm run build` passes, vitest green. Merge to main + push.
