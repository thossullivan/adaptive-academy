---
title: Adaptive Academy — Plan 2: Researcher (fan-out) — Milestone Spec
created: 2026-06-15
status: draft
owner: thossullivan
parent_spec: ./2026-06-15-adaptive-academy-redesign.md   # v1 design (locks the larger picture)
evidence: ../../research/2026-06-15-learning-science-evidence.md
builds_on: ./2026-06-15-adaptive-academy-redesign.md §4.2 (Researcher), §5 (data model), §6.1 (New Topic flow)
---

# Plan 2: Researcher (fan-out) — Milestone Spec

## 0. Goal

Replace the hand-seeded Topic with a real one. Given a topic and a short brainstorm of
intent, a **Researcher** fans out parallel web-search subagents to gather, triage, and
summarize foundational sources into a **Topic Foundation** (overview + key concepts +
prerequisite map) and a **curated, tiered reading list** (`SourceDoc`s) that the user
**reviews and prunes** before it is saved. This proves the fan-out orchestration pattern
and seeds everything the CurriculumDirector (Plan 3) will need.

This is the second vertical slice after the Plan 1 walking skeleton (generation-first
Tutor, already merged to `main`). It reuses every seam Plan 1 established: the
`LLMClient` Protocol + scripted test double, the SQLModel/SQLite + Alembic-batch stack,
the FastAPI factory + dependency-injection pattern, the `AgentEvent` observability trace,
and the SvelteKit/Svelte 5 + Tailwind 4 frontend.

## 1. Scope

### In scope (Definition of Done)
1. **Topic onboarding intake** — a structured brainstorm (goal, prior knowledge, time
   budget) that **creates a Topic** with its captured intent.
2. **Researcher fan-out** — spawn parallel subagents over a topic, **deduplicate by URL**,
   **rank by relevance/authority**, and return a `TopicFoundation` + `SourceDoc[]`
   persisted to SQLite (sources start as `proposed`).
3. **Human-in-the-loop review** — the proposed reading list is surfaced for the user to
   **accept/prune** (confirm-tier) before sources are marked `accepted`.
4. **Observable fan-out** — the orchestration trace records **one event per subagent**
   (plus plan/synthesis/cap events), inspectable like the Tutor's "what the agents did".
5. **Data model + migration** — new `TopicIntent`, `SourceDoc`, `TopicFoundation` tables;
   `AgentEvent` generalized to attach to a Topic; one Alembic (batch-mode) migration.
   **The seeded Topic path and the existing Tutor flow keep working unchanged.**
6. **Tests** — fan-out orchestration is unit-tested with **scripted clients** (no live
   LLM/network); **dedup and ranking are pure, deterministic, and independently tested**;
   the API review round-trip is integration-tested.

### Out of scope (later plans / deferred — do NOT build here)
- ❌ **CurriculumDirector** (turning the foundation into a phased Track). Plan 3.
- ❌ **Assessor**, retention/SRS, build-in-public log. Plan 4+.
- ❌ **Markdown round-trip** of tracks (belongs with the Track, Plan 3).
- ❌ **Conversational, Haiku-narrated multi-turn onboarding.** v1 here is a structured
   intake (a short form / stepper). The warm conversational version is a later polish;
   the structured fields it would collect are identical, so this is forward-compatible.
- ❌ **Live-LLM / live-network tests.** Mirroring Plan 1, the real client paths are thin
   and exercised only by hand; all automated tests use scripted doubles.
- ❌ Wiring the new Topic into the Tutor (a new topic has no Concepts/Track until Plan 3;
   the Tutor continues to run against the seeded topic).

## 2. New decisions (resolved here; flagged for review)

These go slightly beyond the parent spec; rationale given so they can be objected to on
review.

### 2.1 Fan-out mechanism: Anthropic server-side web search, behind a `ResearcherClient` Protocol
The parent spec names the **Claude Agent SDK** for fan-out. For a *single-shot* subagent
whose whole job is "search the web for foundational sources on X and return a structured
list," the **Anthropic Messages API server-side web-search tool** (`web_search`) is the
simpler, lighter mechanism and needs no new heavyweight dependency. Each brief = one
web-search-enabled call = one subagent; parallelism comes from a thread pool.

**We hide this behind a `ResearcherClient` Protocol** (exactly like Plan 1 hid the model
behind `LLMClient`). The Claude Agent SDK can be swapped in later behind the same
Protocol if multi-step autonomous research is ever needed — without touching the
orchestrator, dedup, ranking, persistence, API, or UI. This keeps YAGNI while preserving
the parent spec's "fan-out where it pays off" intent. **Decision: web-search tool for
v1; Protocol seam keeps the SDK swap free.**

### 2.2 Search briefs are template-driven in v1 (not LLM-planned)
The fan-out angles ("foundational papers", "canonical tutorials/courses", "key concepts
& prerequisites", "reference implementations", "critiques & limitations") are produced by
a **deterministic `build_briefs(topic, intent, n)`** function, not an LLM planning call.
This removes one LLM dependency from the hot path, makes the set of subagents
deterministic and testable, and gives the "cap N subagents + log what's dropped" story
for free. LLM-planned briefs are a later enhancement behind the same `SearchBrief` shape.

### 2.3 Determinism despite parallel fan-out
Real subagents run concurrently (thread pool) and may complete in any order. The
orchestrator **sorts the merged raw findings into a canonical order before dedup/rank**,
so the persisted result is identical regardless of completion order. Dedup and ranking
are **pure functions** with explicit, total tiebreaks — fully unit-testable without any
client.

### 2.4 `TopicFoundation` is decoupled from `Track`/`Concept`
This milestone does **not** create the curriculum `Track` or `Concept` rows (that is the
CurriculumDirector's job, Plan 3). The synthesized foundation is stored in its own
`TopicFoundation` table (overview + `key_concepts` JSON + `prerequisite_map` JSON). Plan 3
will read the foundation + accepted sources and materialize `Track`/`Concept`s. This keeps
the seam clean and avoids prematurely coupling research output to the curriculum shape.

## 3. Architecture

```
POST /api/topics            (onboarding intake)
        │  goal, prior_knowledge, time_budget, title
        ▼
   Topic + TopicIntent  ───────────────────────────────────────────┐
        │                                                            │
POST /api/topics/{id}/research                                       │
        ▼                                                            │
  ┌──────────────────────── research_topic() orchestrator ──────────┤
  │  build_briefs(topic, intent, n)         # deterministic angles   │
  │       │  fan-out (ThreadPoolExecutor)                            │
  │       ▼                                                          │
  │  ResearcherClient.search(brief) ×N  ──► RawSource[]   (web search)
  │       │  emit AgentEvent("research:subagent", …) per brief       │
  │       ▼                                                          │
  │  canonicalize → dedupe_by_url → rank_sources → cap   (pure)      │
  │       │  emit AgentEvent("research:capped", …) if dropped        │
  │       ▼                                                          │
  │  synthesize_foundation(topic, intent, ranked, llm)  # LLMClient  │
  │       ▼                                                          │
  │  persist SourceDoc[](status=proposed) + TopicFoundation          │
  │       │  emit AgentEvent("research:done", …)                     │
  └───────┴──────────────────────────────────────────────────────────
        ▼
GET  /api/topics/{id}/sources?status=proposed     # review surface
POST /api/topics/{id}/sources/review              # accept / prune
GET  /api/topics/{id}/foundation
```

**Module boundaries (follow Plan 1 conventions):**
- `llm/researcher_types.py` — `SearchBrief`, `RawSource` dataclasses + `ResearcherClient`
  Protocol.
- `llm/scripted_researcher.py` — `ScriptedResearcherClient` test double (canned
  `RawSource[]` keyed by brief angle; records calls).
- `llm/anthropic_researcher.py` — `AnthropicResearcherClient` (real; Messages API with
  the `web_search` server tool; one call per brief). Thin, not unit-tested live.
- `engine/research.py` — `build_briefs`, `canonicalize_url`, `dedupe_by_url`,
  `rank_sources`, `synthesize_foundation`, and the `research_topic(...)` orchestrator
  returning a `ResearchResult`.
- `api/routes_topics.py` — extend: create-topic (intake), trigger-research,
  list-sources, review-sources, get-foundation.
- `api/deps.py` — add `get_researcher()`.
- `frontend/src/routes/topics/new/` and `frontend/src/routes/topics/[id]/review/`.

## 4. Data model (additions)

```python
class TopicIntent(SQLModel, table=True):          # 1:1 with Topic
    id: Optional[int] = PK
    topic_id: int = FK(topic.id), unique
    goal: str
    prior_knowledge: str
    time_budget: str                              # free text, e.g. "~10 hrs/week"
    created_at: datetime

class SourceDoc(SQLModel, table=True):            # Topic 1—* SourceDoc
    id: Optional[int] = PK
    topic_id: int = FK(topic.id)
    title: str
    url: str
    tier: int                                     # 1 | 2 | 3 (authority tier)
    summary: str = ""
    why: str = ""                                 # why it earns a place in the list
    relevance: float = 0.0                        # subagent-reported, 0..1
    rank: int = 0                                 # 0-based position after rank_sources
    angle: str = ""                               # which brief surfaced it
    status: str = "proposed"                      # proposed | accepted | pruned
    added_by: str = "researcher"
    created_at: datetime

class TopicFoundation(SQLModel, table=True):      # 1:1 with Topic
    id: Optional[int] = PK
    topic_id: int = FK(topic.id), unique
    overview: str                                 # synthesized prose
    key_concepts: list[str] = JSON column         # foundational concepts
    prerequisite_map: dict = JSON column          # {concept: [prereqs]}
    created_at: datetime
```

**`AgentEvent` generalization** (batch-mode migration):
- `conversation_id` becomes **nullable**.
- add nullable **`topic_id`** FK.
- App-level invariant: exactly one of `conversation_id` / `topic_id` is set. The Tutor
  path is unchanged (sets `conversation_id`); research sets `topic_id`.

JSON columns use `sa_column=Column(JSON)` (SQLite `json1` ⇄ Postgres `jsonb`; the
portability discipline from the parent spec §3).

## 5. API surface

| Method | Path | Body / Query | Returns |
|---|---|---|---|
| POST | `/api/topics` | `{title, goal, prior_knowledge, time_budget}` | `TopicOut` (+ intent) |
| POST | `/api/topics/{id}/research` | — | `ResearchOut` (foundation + proposed sources + events) |
| GET | `/api/topics/{id}/sources` | `?status=proposed\|accepted\|pruned` (optional) | `SourceDocOut[]` |
| POST | `/api/topics/{id}/sources/review` | `{accepted_ids:[int], pruned_ids:[int]}` | `SourceDocOut[]` (updated) |
| GET | `/api/topics/{id}/foundation` | — | `FoundationOut` |

- `GET /api/topics` and `GET /api/topics/{id}` (Plan 1) keep working; `TopicOut` gains an
  optional `intent` and `has_foundation` without breaking existing fields.
- Research is **synchronous** for v1 (deterministic + simple). With the real client it may
  take tens of seconds; that is acceptable for a single-user local tool. (Streaming /
  background jobs are a later enhancement.)
- Tests inject scripted clients via FastAPI `dependency_overrides` on `get_researcher`
  and `get_llm`.

## 6. Frontend surface (SvelteKit, Svelte 5 runes, Tailwind 4)

- **`/topics/new`** — intake form (title, goal, prior knowledge, time budget) → `POST
  /api/topics` → `POST /api/topics/{id}/research` with a "Researching…" state → redirect
  to review.
- **`/topics/[id]/review`** — the proposed reading list grouped/sorted by rank: each row
  shows title (link), tier badge, angle, summary, why, and accept/prune controls
  (default accept); a **"Save reading list"** button posts the review. Shows the
  foundation overview + key concepts above the list, and a collapsible fan-out event
  trace (reusing the Plan 1 "what the agents did" affordance).
- Existing `/` (Tutor) is unchanged; add a small link to "New topic".
- `lib/types.ts` + `lib/api.ts` gain typed `createTopic`, `runResearch`, `listSources`,
  `reviewSources`, `getFoundation` mirroring backend field names; a vitest covers the new
  client calls (mock `fetch`), matching the Plan 1 test.

## 7. Testing strategy

- **Pure / deterministic (no clients):** `build_briefs` (count, caps, angle set),
  `canonicalize_url` (scheme/host/www/trailing-slash/tracking-param normalization),
  `dedupe_by_url` (merges dups, keeps the richer record), `rank_sources` (total order,
  stable tiebreak, tier+relevance weighting).
- **Orchestration (scripted clients):** `research_topic` with a `ScriptedResearcherClient`
  (canned `RawSource[]` per angle, including a deliberate cross-brief URL duplicate) +
  `ScriptedLLMClient` (foundation synthesis) → asserts: N subagent events emitted, dups
  removed, ranking order, cap applied + cap event, `SourceDoc`s persisted as `proposed`,
  `TopicFoundation` persisted, result identical across runs (determinism).
- **API integration:** create topic → research (overridden deps) → list proposed →
  review (accept some / prune some) → list accepted; assert statuses and that the seeded
  topic + Tutor endpoints still work.
- **Models:** round-trip the three new tables + the `AgentEvent` topic attachment.
- **Frontend:** vitest for the new api-client calls.
- **Regression guard:** the full Plan 1 suite must stay green.

## 8. Risks / mitigations
- **Fan-out cost & low-quality sources** (parent spec §12.3; 32% bad-output rate for
  unreviewed AI) → capped subagents + capped reading list + **mandatory human prune**
  before `accepted`; log what was dropped.
- **Non-determinism from parallelism** → canonical sort before pure dedup/rank (§2.3).
- **Live web-search variability** → not in automated tests; scripted doubles only.
- **`AgentEvent` nullable change** → batch-mode Alembic migration; both FKs nullable with
  an app-level XOR invariant (no DB CHECK, to stay SQLite/Postgres portable).
