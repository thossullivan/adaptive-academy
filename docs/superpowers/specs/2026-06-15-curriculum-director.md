---
title: CurriculumDirector — Focused Milestone Spec (Plan 3)
created: 2026-06-15
parent_spec: 2026-06-15-adaptive-academy-redesign.md
status: approved-pending-async-objection
---

# CurriculumDirector — Focused Milestone Spec (Plan 3)

> A focused milestone spec carved out of the locked v1 spec
> (`2026-06-15-adaptive-academy-redesign.md`, esp. §4.3, §5, §6.1) and the evidence
> base (`docs/research/2026-06-15-learning-science-evidence.md`, §§1,4,5,7). Same
> shape as Plan 2's `2026-06-15-researcher-fanout.md`. New decisions and the few
> deviations from the v1 spec are in §2 for asynchronous objection.

## 0. Goal

Turn the research output into something the user can actually learn against. Given a
Topic's `TopicFoundation` (overview + key concepts + prerequisite map) and the
**user-accepted** `SourceDoc` reading list (from Plan 2), plus the learner's
`TopicIntent` (goal / prior knowledge / time budget), the **CurriculumDirector**
generates an **editable, phased `Track`**:

```
Track ─* Phase ─* Item            (read | watch | build | write)
        Phase ─1 Deliverable      (the per-phase "🎯 Ship")
Track  ─* Sidebar                 (math_refresh | reading_list | reference)
```

and **materializes the foundation's key concepts into `Concept` rows** (with
`is_load_bearing` set and a seeded `KnowledgeEstimate`) so the **generation-first
Tutor (Plan 1) now runs against a real generated curriculum** instead of the seeded
stub. The Track **round-trips to and from markdown** in the shape of the user's own
`llm-from-scratch-tracker.md`.

This closes the loop: **onboarding → research → curriculum → tutoring.**

## 1. Scope

### In scope
- `POST /api/topics/{id}/curriculum` generates a `Track` with ordered `Phase`s, each
  with typed `Item`s, one `Deliverable` ("🎯 Ship") with acceptance criteria, and the
  Track carries `Sidebar`s.
- The foundation's `key_concepts` (+ `prerequisite_map`) become `Concept` rows under
  the Track with `is_load_bearing` derived deterministically, each with a seeded
  `KnowledgeEstimate` — so `start_conversation` + the Tutor work on a generated Topic.
- **Evidence-driven generation rules**, with the spacing rule **code-enforced**:
  default low-assistance / project-first items; **one 🎯 Ship per phase**; **spaced
  revisits** of load-bearing prerequisites across phases; deliberate-practice drills
  as *supporting*, not the spine.
- **Markdown round-trip:** a pure `track_to_markdown` / `markdown_to_track` inverse
  pair (phases as `##`, items as `- [ ]` checklist lines, `**🎯 Ship:**` deliverables,
  sidebars as labeled `##` sections), proven by a `Track → md → Track` equality test.
- **Editable tracker UI** (`/topics/[id]/track`): view phases/items with a status
  cycle (todo → doing → done), the per-phase deliverable, and sidebars; export to
  markdown. New-topic flow extends review → "Generate curriculum" → track page.
- New data model (`Phase`, `Item`, `Deliverable`, `Sidebar`; `Track` gains
  `overview`) + Alembic batch migration; the Plan 1 (seed/tutor) and Plan 2
  (research/review) paths still work.
- Observable orchestration: one `AgentEvent` (topic-scoped) per generation step.
- Tested: generation unit-tested with a scripted LLM client (deterministic structure
  assertions); the markdown round-trip and the spaced-revisit pass are pure,
  deterministic, independently unit-tested functions; an API integration test covers
  **research → curriculum → Tutor-on-generated-Concept**.

### Out of scope (Plan 4+)
- Assessor / rubric-anchored grading / calibration probes.
- Curated SRS + active-recall retention (`SRSCard`, `RecallPrompt`), scheduling.
- `Rubric`, `ReferenceAnchor`, `Assessment`, `ReflectionEntry` tables.
- Build-in-public log, streaming, auth.
- Re-running the Researcher (this milestone **consumes** Plan 2's stored output).
- **Fan-out** curriculum generation (single LLM call for v1 — see §2.1).
- "Adapt mode" (re-sequence on Assessor gap) — there is no Assessor yet.
- Linking each read-item to a specific `SourceDoc` (`Item.source_doc_id` stays a
  nullable DB-only field for v1) — see §2.4.

## 2. New decisions (deviations from the v1 spec — documented for objection)

### 2.1 Single structured LLM call, not fan-out
The v1 spec leaves generation style open; Plan 2 proved the fan-out pattern. For the
CurriculumDirector we generate the whole Track in **one structured `LLMClient.complete`
call** that returns JSON, mirroring `research.synthesize_foundation`. Rationale: a Track
is a single coherent artifact (phase ordering, the spaced-revisit thread, and the one
deliverable-per-phase constraint are *global* properties that a single call reasons
about coherently); fan-out-per-phase adds a coordination/merge layer with no clear v1
payoff. Fan-out is the natural next step if phases grow deep — revisit then.

### 2.2 The spaced-revisit rule is CODE-ENFORCED, not LLM-trusted
"Spaced revisits of load-bearing prerequisites across phases" is the load-bearing
evidence rule (§§1,5,6). Rather than trust the LLM to honor it, a pure deterministic
pass `insert_spaced_revisits(phases, load_bearing)` runs **after** parsing the LLM
output and **guarantees** every load-bearing concept spans **≥2 distinct phases**
whenever the Track has ≥2 phases (injecting lightweight `write`-type "revisit &
self-explain" items into a *different* phase where the LLM didn't — a concept the LLM
left in only the last phase is revisited in an earlier one; an unreferenced concept is
touched in the first and last phases). With a single phase, spacing is impossible, so
it guarantees only one touch. This parallels Plan 1's **code-enforced attempt-gate** and Plan 2's
**deterministic dedup/rank** — the pedagogy that matters is enforced in code and unit
tested, not left to model goodwill. The pass emits a `curriculum:spaced` event so the
enforcement is observable.

### 2.3 `is_load_bearing` derived from the prerequisite map
A generated `Concept` is **load-bearing iff it appears as a prerequisite** of some
other concept in `TopicFoundation.prerequisite_map` (i.e., it shows up in any value
list — something depends on it). Deterministic, pure, testable; it is the signal the
spaced-revisit pass keys on. (The v1 spec defers load-bearing detection to the
Assessor; until the Assessor exists, the prerequisite graph is the principled proxy.)

### 2.4 Markdown round-trip is a defined inverse pair over the Track model
The serializer **defines** the canonical format; the parser is its exact inverse and
accepts **exactly what the serializer emits** (same stance as `research.py` parsing
only its own JSON). The round-trip test asserts `markdown_to_track(track_to_markdown(t))
== t` structurally over: Track `title` + `overview`; ordered Phases (`title`,
`est_hours`, `flags`); ordered Items (`type`, `status`, `text`); each Phase's
Deliverable (`kind`, `text`, `acceptance_criteria`); ordered Sidebars (`kind`, `title`,
`body`). The format deliberately **resembles** `llm-from-scratch-tracker.md` but is a
defined subset — we are **not** parsing arbitrary hand-written markdown. DB-only
metadata outside the round-trip contract: `Item.links`, `Item.source_doc_id`,
`Item.concept_refs`, `Deliverable.artifact_url`, `Deliverable.review_verdict`,
`Concept`/`KnowledgeEstimate`. (Items still carry `concept_refs` in the DB — that is
how the spaced-revisit pass and the Tutor wiring work — they are simply not serialized
to markdown in v1.)

### 2.5 KnowledgeEstimate seeded at level="high"
Each generated `Concept` gets a `KnowledgeEstimate(level="high", confidence=0.5)`,
mirroring `seed.py` and the expert-user default in `levels.py` (`compute_levels(None)`
→ low assistance / high challenge). This makes the Tutor immediately run in the correct
low-assistance stance on a freshly generated Topic, and keeps `Concept.estimate`
non-null for the existing `_levels_for` path.

### 2.6 Consumes accepted sources + stored foundation; never re-runs research
Generation requires a stored `TopicFoundation` **and** at least one `SourceDoc` with
`status == "accepted"` (the human-in-the-loop gate from Plan 2). If either is missing →
`400`. It reads Plan 2's output; it does not call the Researcher.

## 3. Architecture & module boundaries

Respects the existing `models → engine → agents(n/a) → api` layering; the engine module
mirrors `engine/research.py` (pure helpers + a single orchestrator that takes injected
clients, persists, traces, and returns a result dataclass).

```
POST /api/topics/{id}/curriculum
  routes_topics.generate_curriculum
    └─ engine/curriculum.generate_curriculum(session, topic, intent, foundation,
                                             accepted_sources, *, llm)
         build_curriculum_prompt(...)            # pure: system + user msg
         llm.complete(...)                        # ONE structured call → JSON
         parse_curriculum_json(text) -> PlanDraft # pure
         load_bearing_concepts(foundation)        # pure (§2.3)
         insert_spaced_revisits(phases, lb)       # pure, CODE-ENFORCED (§2.2)
         → persist Track(overview)+Phase[]+Item[]+Deliverable[]+Sidebar[]
                   +Concept[]+KnowledgeEstimate[]   (§2.5)
         → emit AgentEvent per step (topic-scoped)
         → CurriculumResult(track, phases, items, deliverables, sidebars,
                            concepts, events)

engine/track_markdown.py  (pure, no DB, no LLM)
  track_to_markdown(TrackView) -> str
  markdown_to_track(str) -> TrackView          # exact inverse (§2.4)
```

**Module responsibilities**
- `engine/curriculum.py` — prompt building, JSON parse, load-bearing derivation,
  spaced-revisit enforcement, the orchestrator, result dataclasses.
- `engine/track_markdown.py` — the pure serialize/parse inverse pair over a plain
  `TrackView`/`PhaseView`/`ItemView`/`DeliverableView`/`SidebarView` dataclass tree
  (decoupled from SQLModel so it is trivially testable and reusable by export/import).
- `models.py` — `Phase`, `Item`, `Deliverable`, `Sidebar`; `Track.overview`.
- `api/routes_topics.py` — `POST/GET /curriculum`, `GET /curriculum.md`,
  `POST /curriculum/import`; `api/routes_items.py` — `PATCH /api/items/{id}` (status).
- Frontend — `/topics/[id]/track` page; review page "Generate curriculum" action.

## 4. Data model additions (SQLModel / SQLite)

```python
# Track gains one column:
class Track:
    ... (id, topic_id, title unchanged)
    overview: str = ""                      # intro prose (markdown round-trip)
    phases:   list[Phase]   = Relationship(back_populates="track")
    sidebars: list[Sidebar] = Relationship(back_populates="track")
    # concepts: list[Concept] already exists

class Phase(SQLModel, table=True):
    id: Optional[int] = primary_key
    track_id: int = FK track.id
    title: str
    position: int = 0                        # 0-based order
    est_hours: str = ""                      # free label, e.g. "Weeks 2–5"
    flags: list[str] = JSON []               # subset of {optional, stretch, parallel_track}
    items: list[Item]      = Relationship(back_populates="phase", ordered by position)
    deliverable: Optional[Deliverable] = Relationship(back_populates="phase")

class Item(SQLModel, table=True):
    id: Optional[int] = primary_key
    phase_id: int = FK phase.id
    text: str
    type: str = "read"                       # read | watch | build | write
    status: str = "todo"                     # todo | doing | done
    position: int = 0
    links: list[str] = JSON []               # DB-only (§2.4)
    source_doc_id: Optional[int] = FK sourcedoc.id, nullable   # DB-only, v1 unused
    concept_refs: list[str] = JSON []        # concept names this item exercises (DB-only)

class Deliverable(SQLModel, table=True):
    id: Optional[int] = primary_key
    phase_id: int = FK phase.id, unique      # one 🎯 Ship per phase
    kind: str = "blog"                       # blog | repo | model | talk | ablation
    text: str
    acceptance_criteria: list[str] = JSON []
    artifact_url: str = ""                    # DB-only
    review_verdict: str = ""                  # DB-only

class Sidebar(SQLModel, table=True):
    id: Optional[int] = primary_key
    track_id: int = FK track.id
    phase_id: Optional[int] = FK phase.id, nullable   # v1 always track-level (None)
    kind: str                                 # math_refresh | reading_list | reference
    title: str
    body: str = ""                            # markdown
    position: int = 0
```

JSON columns use `sa_column=Column(JSON)` exactly as `TopicFoundation` does.

**Migration** (`alembic revision`, down_revision `58c3f587d8a0`): create `phase`,
`item`, `deliverable`, `sidebar`; `batch_alter_table('track')` to add `overview`
(`nullable=True` / server_default `''` so the seeded Track row is satisfied). Add
`import sqlmodel`; round-trips upgrade→downgrade→upgrade. `just seed` + the Plan 1/2
flows still work afterward.

## 5. API surface

| Method | Path | Body | Returns | Notes |
|---|---|---|---|---|
| POST | `/api/topics/{id}/curriculum` | — | `CurriculumOut` | 404 topic; 400 if no foundation or no accepted sources; generates + persists |
| GET | `/api/topics/{id}/curriculum` | — | `CurriculumOut` | 404 if no Track |
| GET | `/api/topics/{id}/curriculum.md` | — | `text/plain` | `track_to_markdown` export |
| POST | `/api/topics/{id}/curriculum/import` | `{markdown}` | `CurriculumOut` | replaces the Track from markdown (`markdown_to_track`) |
| PATCH | `/api/items/{item_id}` | `{status?, text?}` | `ItemOut` | editable UI; 404 if missing |

`CurriculumOut`: `{ track: {id, title, overview}, phases: [{id, title, position,
est_hours, flags, items: [ItemOut], deliverable: DeliverableOut?}], sidebars:
[SidebarOut], concepts: [ConceptOut], events: [EventOut] }`. `ItemOut`: `{id, text,
type, status, position}`. `DeliverableOut`: `{id, kind, text, acceptance_criteria}`.
`SidebarOut`: `{id, kind, title, body, position}`. `TopicOut` gains
`has_track: bool = False`.

## 6. Frontend surface

- **`/topics/[id]/track`** — loads `GET /curriculum`; renders Track title + overview,
  each Phase (title, est_hours, flags) with its Items (status cycle button
  todo→doing→done via `PATCH /api/items/{id}`), the 🎯 Ship deliverable + acceptance
  criteria, and the Sidebars; an "Export markdown" control hitting `/curriculum.md`; a
  collapsible "What the agents did" event trace (reuse the Plan 2 pattern).
- **Review page** (`/topics/[id]/review`) — after "Save reading list", a "Generate
  curriculum →" button calls `generateCurriculum(topicId)` then `goto('/topics/{id}/track')`.
- `lib/types.ts` + `lib/api.ts` gain `Track/Phase/Item/Deliverable/Sidebar/CurriculumResult`
  types and `generateCurriculum/getCurriculum/exportCurriculumMd/updateItem` clients,
  following the existing `j<T>` fetch pattern. `lib/api.test.ts` covers the new clients.

## 7. Testing strategy

- **Pure / deterministic (no LLM, no network):**
  - `load_bearing_concepts` — derives load-bearing set from a prerequisite map.
  - `insert_spaced_revisits` — every load-bearing concept ends up referenced in ≥2
    phases (or gets an injected revisit); idempotent; no-op when already spaced;
    handles 0-reference and single-phase edge cases.
  - `parse_curriculum_json` — parses well-formed JSON; strips ```json fences; sane
    defaults on missing keys (mirror `_parse_foundation_json`).
  - `track_to_markdown` / `markdown_to_track` — **round-trip equality** over a
    hand-built `TrackView`; plus a golden-format assertion that the export uses `##`
    phases, `- [ ]` items, `**🎯 Ship:**`, and labeled sidebars.
- **Orchestration (scripted clients):** `generate_curriculum` with a
  `ScriptedLLMClient` returning a fixed curriculum JSON → asserts Track/Phases/Items/
  Deliverables/Sidebars/Concepts persisted, `is_load_bearing` correct, estimates
  seeded, spaced revisits present, one event per step, all events topic-scoped.
- **API:** `POST /curriculum` happy path + the two 400s + the 404; `PATCH /api/items`
  status update; `GET /curriculum.md` returns markdown.
- **Integration (the loop):** seed/scripted research → `POST /curriculum` →
  `POST /api/conversations` on a generated `Concept` → `POST .../messages` with a
  scripted Tutor → asserts a tutor reply + levels (assistance=low) on generated data.
- **Regression:** existing 38 backend + 3 frontend tests stay green; migration
  round-trips; `just seed` still seeds.

Live paths (real `AnthropicLLMClient` generation) stay thin and hand-verified, like
Plans 1–2 (no real API key in CI).

## 8. Risks

- **Markdown ambiguity** → mitigated by §2.4 (parser is the serializer's exact inverse
  over a defined subset; not general markdown).
- **Migration on the seeded Track row** → add `overview` nullable/with default; verify
  `just seed` + downgrade/upgrade.
- **LLM returns malformed/empty phases** → `parse_curriculum_json` defaults defensively;
  `insert_spaced_revisits` and persistence tolerate empty phase lists (orchestrator
  still emits events and returns a (possibly thin) Track); the 400 guards run first.
- **Over-scaffolding drift** (anti-evidence) → the prompt encodes low-assistance/
  project-first explicitly; deliberate-practice items are constrained to *supporting*.
```
