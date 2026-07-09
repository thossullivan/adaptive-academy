---
title: Program Layer — long-horizon, verified-depth learning programs
created: 2026-07-09
status: approved for planning
companion_to:
  - 2026-06-15-adaptive-academy-redesign.md
  - ../../research/2026-06-15-learning-science-evidence.md
---

# Program Layer

## 1. Problem & goal

Adaptive Academy today is built around a single **Topic** (research fan-out →
phased Track → generation-first Tutor → Assessor → remediation → retention).
That unit is sized for weeks-scale learning. A substantial goal — the motivating
example is **PhD-level CS preparation with a focus on custom LLM models** — is
months-to-years, spans many interlocking topics (math foundations →
architectures → training → primary literature → original work), and demands
verification of *depth*, not course completion.

The evidence base (`docs/research/2026-06-15-learning-science-evidence.md`)
defines the success bar for such a goal:

- **Core metric: delayed, unassisted performance** (§8.2/§8.6) — in-session,
  assisted success is a vanity metric; self-reported confidence is untrustworthy
  (§8.4, illusion of competence).
- **Primary evidence: authentic generative artifacts** (§2/§4) — build and
  teach artifacts, graded anchored; quals-style quizzing is a thin spaced
  scaffold over load-bearing prerequisites only.
- **Capstone bar: reproduce-then-extend on real literature** — the transfer
  task that operationally defines "research-ready."

This spec adds a **Program layer above Topics** that owns the long horizon:
sequencing, milestone gates computed from that evidence, and knowledge
carryover across topics. It deliberately does **not** build the
research-apprenticeship machinery (critical paper-reading probes,
reproduce-then-extend deliverables) — that is the follow-up spec; a Program can
name a capstone milestone before its machinery exists.

## 2. Key decisions

1. **Program layer above Topics** (not a mega-Topic, not federated loose
   topics). Existing tables keep their meaning; everything here is additive.
2. **Milestone-level DAG, not topic-level.** A program is naturally staged
   (quals-style); dependencies live between Milestones via `depends_on`.
   Topics within a milestone are unordered. Topic-level DAGs are YAGNI.
3. **Researched proposal, user edits** (the Plan 2 human-in-loop pattern at
   program scale). A program-level research fan-out surveys real PhD curricula,
   quals syllabi, canonical courses, and practitioner roadmaps → drafts
   milestones + candidate topics + success criteria, each sourced → user
   prunes/reorders/edits on a review page before anything is materialized.
4. **Lazy topic materialization.** Accepting a program creates Topic *stubs*
   only. The full topic pipeline (research → curriculum → concepts) runs when
   the user starts that topic — cost paid just-in-time, and the curriculum is
   generated against *then-current* knowledge estimates (the program-scale
   application of the expertise-reversal principle: don't plan assistance
   levels years ahead).
5. **Verified gates with explicit override — nag, never block.** A gate
   "passes" only on evidence (delayed unassisted verification + artifact-grade
   assessment per load-bearing concept). The user can override with a required
   logged reason; the milestone shows "unverified" permanently. Starting
   next-milestone topics is always possible — the gate's power is honest
   bookkeeping, not a lock (autonomy for an expert learner; calibration data
   preserved).
6. **Gate verdicts are pure functions over existing evidence rows**
   (`Assessment`, `RecallPrompt`) — no new assessment machinery, no LLM call,
   deterministic and testable. This parallels the project's code-enforced
   invariants (Plan 1 attempt-gate, Plan 3 spaced-revisit rule, Plan 4 rules
   layer).
7. **Cross-topic knowledge carryover via `ConceptAlias`** — name-match linking
   (Plan 6's case-insensitive pattern) of new concepts to prior ones inside
   the same program; linked concepts seed their `KnowledgeEstimate` from the
   prior concept's current level instead of the cold default.

## 3. Data model (all additive)

- **`Program`** — `id`, `title`, `goal_statement` (why deep / why this),
  `status` (`active|paused|done`), `created_at`, `updated_at`.
- **`ProgramIntent`** — `program_id` (unique FK), structured intake mirroring
  `TopicIntent`: `target_depth`, `prior_knowledge`, `weekly_time_budget`,
  `horizon`, `focus_area`.
- **`Milestone`** — `program_id` FK, `title`, `success_criteria` (text,
  verifiable phrasing), `order_index`, `gate_status`
  (`open|passed|overridden`), `depends_on` (JSON list of milestone ids),
  `override_reason` (nullable).
- **`ProgramTopicLink`** — `milestone_id` FK, `topic_id` FK, `status`
  (`proposed|stub|started|done`), `proposed_title`/`proposed_angle` (for
  pre-materialization candidates), `sources` (JSON, from the research pass).
- **`ConceptAlias`** — `program_id` FK, `canonical_name`, `concept_id` FK.
  One row per (program, concept) membership in a canonical concept identity.

`Topic`, `Track`, `Concept`, `KnowledgeEstimate`, `Assessment`, `RecallPrompt`
are untouched.

## 4. Flows

### 4.1 Creation

1. `/programs/new` — structured intake form → `Program` + `ProgramIntent`.
2. **Program-level research fan-out** (reuses the `ResearcherClient` seam and
   the Plan 2/9 fan-out muscle; works in both API-key and agent_sdk modes).
   Program-shaped angles: (a) real PhD curricula & quals syllabi, (b) canonical
   courses for the focus area, (c) practitioner roadmaps, (d) primary-literature
   reading lists, (e) prerequisite structures. Output parsed into proposed
   `Milestone`s + candidate topics (`ProgramTopicLink status=proposed`) +
   suggested `success_criteria`, each with sources.
3. `/programs/[id]/review` — prune/reorder/edit milestones and topic
   candidates (same accept/prune verbs as SourceDoc review). Accepting
   finalizes milestones and flips accepted links to `status=stub`.
4. Starting a stub topic runs the normal Topic pipeline (intent pre-filled
   from the program context) and flips the link to `started`.

### 4.2 Gate evaluation

- The gate for a milestone watches the **load-bearing concepts**
  (`Concept.is_load_bearing`) of its started topics.
- **Pass condition, per load-bearing concept:**
  - (a) **delayed verification** — a `RecallPrompt` graded *held* where the
    grading occurred ≥7 days after the concept's last non-recall assessment
    (the existing Decay Check machinery is exactly this; the gate requires
    rather than suggests it), **and**
  - (b) **artifact-grade evidence** — ≥1 `Assessment` of kind
    `artifact_review | teach | productive_failure` with score ≥ threshold
    (default 0.7, constant in `engine/gates.py`).
- `engine/gates.py` exposes pure functions: `concept_evidence(...)` →
  per-concept verdict (`verified | stale | never_probed_cold | weak_artifact`),
  `gate_verdict(...)` → milestone verdict. No LLM calls.
- A milestone with zero started topics or zero load-bearing concepts is
  `open` with an explicit "no evidence yet" verdict (never vacuously passed).

### 4.3 Override

`POST /api/programs/{pid}/milestones/{mid}/override` with required free-text
`reason` → `gate_status="overridden"`, `override_reason` stored, logged as an
`AgentEvent` (`program:gate_override`). UI shows a permanent "⚠ unverified"
marker on the milestone. No un-override in v1 (re-verification can still flip
it to `passed`; passing supersedes the override marker).

### 4.4 Knowledge carryover

When the CurriculumDirector materializes concepts for a topic that belongs to
a program: for each new concept, case-insensitive name match against
`ConceptAlias.canonical_name` rows of the same program. On match, the new
concept joins the alias group and its `KnowledgeEstimate` is **seeded from the
current level of the most recently assessed concept in the group** (instead of
the cold default). No match → a new alias group is created with the concept's
name as canonical. LLM-assisted fuzzy matching is deferred until name-matching
demonstrably misses.

Decay Checks on earlier topics' concepts continue over the program's horizon,
keeping seeded estimates honest.

## 5. API

- `POST /api/programs` (intake) · `GET /api/programs` · `GET /api/programs/{id}`
- `POST /api/programs/{id}/research` (fan-out; resilient per-angle, Plan 9
  pattern) · `GET /api/programs/{id}/proposal`
- `POST /api/programs/{id}/accept` (finalize review edits → stubs)
- `POST /api/programs/{id}/topics/{link_id}/start` (materialize stub)
- `GET /api/programs/{id}/gate/{milestone_id}` (evidence table, pure read)
- `POST /api/programs/{pid}/milestones/{mid}/override`

## 6. UI

- **`/programs`** — list. **`/programs/[id]`** — the program map: milestone
  rail in the Observatory idiom (a program is a *long voyage* with named legs,
  consistent with the fleet/wayfinding metaphor), per-milestone gate evidence
  table (concept × {delayed ✓, artifact ✓}), "start next topic" affordance,
  override affordance with reason input.
- **Today page**: a program strip — current milestone, the next gate's
  unverified concepts (turns the long-horizon goal into today's concrete
  probes).
- Topic pages: a small "part of {Program} / {Milestone}" breadcrumb. Otherwise
  unchanged.

## 7. Errors & resilience

- Research fan-out follows Plan 9: a failing angle is recorded
  (`program_research:subagent_error`) and the others are kept; total failure →
  legible 502 per the existing handler contract.
- Gate and evidence endpoints are pure DB reads — no LLM fault modes.
- Override without a reason → 400. Gate query for a milestone whose
  dependencies are unmet is allowed (read-only; the DAG only affects UI
  ordering and nags, never blocks).

## 8. Testing

- **Pure gate logic**: evidence-combination matrix → verdicts (no delayed
  recall; recall too early; decayed vs held; artifact below/above threshold;
  zero topics; zero load-bearing concepts).
- **Alias seeding**: match → estimate seeded from most-recent group member;
  no match → cold default + new group; cross-program isolation.
- **Lazy materialization**: accept creates stubs only (no Topic pipeline
  side-effects); start runs the pipeline once (idempotent guard).
- **Override**: reason required, AgentEvent logged, later verification can
  supersede.
- **Research fan-out**: scripted `ResearcherClient` double (by-angle,
  thread-safe — Plan 2 pattern); single-angle failure keeps others.
- Migration round-trips clean and after-seed, per convention.

## 9. Non-goals (this spec)

- Paper-reading probes and reproduce-then-extend deliverables (follow-up
  "research-apprenticeship" spec — it will plug into Milestones as the
  capstone's machinery).
- Auto-gating actions (auto-remediation, auto-scheduling) — human in loop.
- Multi-program interactions; sharing topics between programs.
- Topic-level dependency DAGs.
- LLM-assisted concept alias matching (name match first; upgrade on evidence).

## 10. Open questions (carried into planning)

- Threshold tuning: 0.7 artifact score and 7-day delay are defaults to tune
  from dogfood data, not evidence-derived constants.
- Whether the program strip on Today should surface at most one probe per day
  (friction budget) — decide during frontend planning.
