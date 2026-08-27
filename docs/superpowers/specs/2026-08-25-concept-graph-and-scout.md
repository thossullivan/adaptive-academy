---
title: Concept Graph & Scout — a traversable, bi-temporal concept graph and evidence-cited topic suggestions
created: 2026-08-25
status: approved for planning
companion_to:
  - 2026-08-25-memory-retrieval.md
  - 2026-07-09-program-layer.md
  - 2026-07-10-map-revision.md
---

# Concept Graph & Scout

**Status:** Approved for planning. Depends on Tasks 1–4 of the memory-retrieval plan.

## Goal

1. **Materialize the concept graph.** Turn the edges that exist today only inside JSON
   blobs (`TopicFoundation.prerequisite_map`, `Milestone.depends_on`, `ConceptAlias`
   groups) into one queryable, **bi-temporal** `ConceptEdge` table, traversed with SQLite
   recursive CTEs. No graph database.
2. **Bridge corpus and graph.** A `chunk_concept` link table tags retrieval chunks with the
   concepts they mention, so graph traversal reaches documents and retrieval can expand
   along the graph.
3. **Use the graph.** Remediation walks prerequisites to find the weakest ancestor; the
   Constellation map gets server-computed edges; retrieval adds 1-hop neighbor names to a
   grounding query.
4. **Scout.** Recommend new topics from evidence — frontier concepts, orphan terms in the
   learner's own writing, orphan vault notes, and paper-probe "what would you extend"
   answers — as reviewable `TopicSuggestion` rows. Nothing is created without a click.

## Why

- The `/map` page builds prerequisite edges **client-side** by lenient name matching over
  `prerequisite_map`. `remediate.py` plans from gap text alone. Nothing can ask "what are
  the prerequisites of concept 42" without parsing JSON in Python.
- Map Revision already proposes a reviewed diff to a Program's map, and lazy topic stubs
  already spawn from milestones. What is missing is a **trigger** and an **evidence source**
  for new topics. The learner's own record (now indexed by the memory layer) is that source.
- Personal-scale graphs (< 10K nodes, < 50K edges) traverse in microseconds with a recursive
  CTE; graph databases pay off past ~100K entities with depth-4+ traversals, concurrent
  writers, or Cypher-style pattern matching. None applies. The embedded option (Kuzu) was
  archived 2025-10-10; its fork LadybugDB targets a graph lakehouse and is young. Zep's
  Graphiti — the reference temporal-KG memory — requires a Neo4j/FalkorDB server. We borrow
  its one transferable idea: **bi-temporal edges**, so Map Revision invalidates instead of
  deletes.

## Scope

**In:** `ConceptEdge` + `ChunkConcept` tables and migration; population from
`prerequisite_map`, alias groups, and accepted `MapChange`s; recursive-CTE traversal
helpers; graph-aware remediation; `/api/topics/{id}/graph` for the map; neighbor-name query
expansion in `memory.retrieve`; `engine/scout.py` with deterministic candidate generation
and one LLM ranking call; `TopicSuggestion` table, API, dashboard card; tests.

**Out:** LLM entity/relation extraction from documents; edge weights learned from
performance; a graph editor UI (accept/reject only, via Map Revision); cross-program
graphs; auto-creating topics or milestones.

## Data Model

```python
class ConceptEdge(SQLModel, table=True):
    """Directed, typed, bi-temporal edge between two concepts."""
    id: Optional[int] = Field(default=None, primary_key=True)
    src_concept_id: int = Field(foreign_key="concept.id")
    dst_concept_id: int = Field(foreign_key="concept.id")
    kind: str                 # prerequisite (src requires dst) | related | alias
    weight: float = 1.0
    origin: str               # researcher | revision | alias | learner
    origin_ref: str = ""      # "foundation:<topic_id>" | "mapchange:<id>" | "alias:<id>"
    valid_from: datetime = Field(default_factory=_now)   # when true in the map
    valid_until: Optional[datetime] = None               # NULL = current
    recorded_at: datetime = Field(default_factory=_now)  # when we learned it


class ChunkConcept(SQLModel, table=True):
    """Which concepts a chunk mentions (string-matched at index time; no LLM)."""
    id: Optional[int] = Field(default=None, primary_key=True)
    chunk_id: int = Field(foreign_key="chunk.id")
    concept_id: int = Field(foreign_key="concept.id")
    hits: int = 1             # mention count in the chunk


class TopicSuggestion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    program_id: Optional[int] = Field(default=None, foreign_key="program.id")
    title: str
    rationale: str
    candidate_kind: str       # frontier | orphan_term | orphan_note | extension
    evidence: list[dict] = Field(default_factory=list, sa_column=Column(JSON))
                              # [{"kind": "chunk", "ref": "message:12"}, {"kind": "concept", "id": 42}, ...]
    score: float = 0.0
    status: str = "proposed"  # proposed | accepted | dismissed
    created_at: datetime = Field(default_factory=_now)
    decided_at: Optional[datetime] = None
```

Indexes: `conceptedge(src_concept_id, valid_until)`, `(dst_concept_id, valid_until)`,
unique `chunkconcept(chunk_id, concept_id)`, `topicsuggestion(status, program_id)`.

## Population

| origin | when | rule |
|---|---|---|
| `researcher` | `curriculum.generate_curriculum` right after the `Concept` rows are created from `key_concepts` | for each `name -> [prereqs]` in `prerequisite_map`, resolve both names to `Concept` rows in the track (exact, then `aliases.normalize_name`); insert `prerequisite` edges; unresolved names are logged in one `AgentEvent`, never invented. If the track already had current `researcher` edges (curriculum regenerated), set `valid_until = now` on them first — the old map is history, not deleted |
| `alias` | `aliases.apply_program_aliases` | pairwise `alias` edges inside each alias group (undirected: insert both directions) |
| `revision` | `revision.apply_change` for `prune_topic` | set `valid_until = now` on every current edge touching the pruned topic's concepts; `origin_ref = f"mapchange:{change.id}"` recorded on an `AgentEvent`, the edges keep their original `origin`. `MapChange` has no prerequisite-editing kind today, so no edge is *inserted* by revision; `Milestone.depends_on` stays as JSON (milestone-level, not concept-level). Rejected changes touch nothing |
| backfill | one-shot `just graph-backfill` (calls `engine/graph.backfill(session)`) | re-derives `researcher` + `alias` edges for existing data, idempotent on `(src, dst, kind, valid_until IS NULL)` |

`ChunkConcept` rows are written inside `memory.index_text` (memory plan Task 2 gains a hook):
for the chunk's topic, match each `Concept.name` and each `ConceptAlias.canonical_name`
as a whole-word, case-insensitive pattern against `context + text`; store `hits`. Names
shorter than 4 characters are skipped.

## Traversal (`engine/graph.py`)

```python
def ancestors(session, concept_id, *, kind="prerequisite", max_depth=3, at=None) -> list[tuple[int, int]]  # (concept_id, depth)
def descendants(session, concept_id, *, kind="prerequisite", max_depth=3, at=None) -> list[tuple[int, int]]
def neighbors(session, concept_id, *, kinds=("prerequisite", "related", "alias"), at=None) -> list[int]
def frontier(session, track_id, *, solid_level="solid") -> list[int]   # solid concepts with ≥1 current neighbor outside any track
def weakest_ancestor(session, concept_id) -> tuple[int, float] | None  # lowest KnowledgeEstimate among ancestors
```

One recursive CTE, parameterized by direction and `valid_until IS NULL` (or `valid_from <=
at < coalesce(valid_until, at+1)` when `at` is given). `max_depth` is capped at 6.

## Uses

- **Remediation.** `remediate.remediate_concept` calls `weakest_ancestor`; when its estimate
  is below the target concept's, the remediation prompt names it and the plan targets the
  ancestor's phase first. Emits `AgentEvent(kind="remediate:ancestor")`.
- **Map.** `GET /api/topics/{id}/graph` → `{nodes: [...], edges: [{src, dst, kind, weight}]}`
  from current edges. The `/map` page uses it and drops client-side name matching.
- **Retrieval.** `memory.expand_query` appends the names of `neighbors(concept_id)` (cap 3)
  after the alias, so grounding for "attention" also matches "softmax" notes.
- **Gates.** No change. Gates stay evidence-only; the graph never passes a milestone.

## Scout (`engine/scout.py`)

Trigger: `POST /api/programs/{id}/scout` (dashboard button) and automatically after every
`SCOUT_EVERY_N_ASSESSMENTS = 25` new `Assessment` rows in the program (checked in the
assess route, runs inline, capped at 10 s of candidate generation).

Deterministic candidates, no LLM:

1. **frontier** — `graph.frontier` per track; evidence = the solid concept ids and the
   outside neighbor names.
2. **orphan_term** — over `learner_output` + `tutor_turn` chunks for the program's topics,
   count capitalized multi-word terms and backticked identifiers that match no
   `Concept`/`ConceptAlias` name (whole-word); keep terms with ≥ 3 occurrences across ≥ 2
   sources; evidence = chunk refs.
3. **orphan_note** — vault notes (`vault_note` chunks) with zero `ChunkConcept` rows across
   all topics, grouped by note; evidence = file URIs.
4. **extension** — `paper` / `learner_output` chunks with `meta.role == "extension"`;
   evidence = the probe ids.

Then **one** LLM call (`SCOUT_RANK` prompt, `reasoning` model) over a ≤ 4k-token digest of
the candidates + the Program's goal statement + current milestone titles. It returns at most
5 `{title, rationale, candidate_kind, evidence_indexes, score}` items, forced structured
output, evidence indexes validated against the digest (an item citing nothing is dropped).
Rows are upserted by normalized title; a dismissed title is not re-proposed for 30 days.

Accept → a `ProgramTopicLink(milestone_id=<picked>, status="stub", proposed_title=title,
why=rationale, added_by="scout")` — the existing lazy-stub path; the learner starts it from
the Program page exactly like a revision-added topic. Dismiss → `status="dismissed"`.
Both emit `AgentEvent(program_id=...)`.

"Solid" for the frontier means `gates.evaluate_concept(...)` returns a passing
`ConceptEvidence` (same rule the milestone gate uses). `weakest_ancestor` excludes
unassessed ancestors and orders assessed ancestors by the latest `Assessment` score's
derived level (`low < medium < high`), then by that score.

## API

- `GET /api/topics/{id}/graph` (above)
- `GET /api/concepts/{id}/ancestors?depth=`, `GET /api/concepts/{id}/neighbors`
- `POST /api/programs/{id}/scout` → `{suggestions: [...], candidates: {frontier: n, orphan_term: n, orphan_note: n, extension: n}}`
- `GET /api/programs/{id}/suggestions?status=`
- `POST /api/suggestions/{id}/accept` body `{milestone_id?}`; `POST /api/suggestions/{id}/dismiss`

## UI

- Dashboard: a "Scout found N" card listing proposed suggestions with rationale and an
  evidence popover; Accept / Dismiss.
- `/map`: edges from the API; a legend for `prerequisite` vs `related`; an ancestor
  highlight on select.
- `/programs/[id]`: the same suggestions list under the milestone map.

## Testing (scripted backend — zero live API)

- `test_graph_edges.py` — population from a fixture `prerequisite_map` (resolved, normalized,
  unresolved logged); alias groups produce both directions; backfill is idempotent.
- `test_graph_traversal.py` — a 6-node fixture: `ancestors` depth cap, cycle safety (`UNION`
  dedup), bi-temporal filter excludes an invalidated edge and includes it with `at=` before
  invalidation; `frontier` and `weakest_ancestor`.
- `test_revision_edges.py` — applying a prerequisite-removing `MapChange` sets `valid_until`
  and inserts nothing; rejecting touches nothing.
- `test_remediate_ancestor.py` — weak ancestor changes the target phase and the prompt.
- `test_chunk_concept.py` — index a chunk mentioning two concept names → two link rows;
  short names skipped; alias name matches.
- `test_scout_candidates.py` — each of the four generators on fixtures; dismissed-title
  cooldown.
- `test_scout_rank.py` — `ScriptedLLMClient` returns 6 items, one with no evidence → 5
  stored; evidence indexes map back to refs; second run upserts by title.
- `test_api_graph.py`, `test_api_scout.py`.
- Frontend: vitest for the suggestion card and the map legend.

## Migration

One revision after the memory-retrieval revision. Three `op.create_table`s with inline
FKs (new tables). No `ALTER` on existing tables. No `batch_alter_table`.

## Non-goals / future

- Learned edge weights from assessment outcomes.
- LLM-extracted relations from vault notes or papers.
- Program-to-program concept identity.
- Auto-accepting suggestions.

## Open questions (carried into planning)

1. Should `related` edges come from anywhere in this slice? Default: only from
   `prerequisite_map` when the Researcher emits a `related` list (it does not today) — so
   effectively none until the research prompt is extended.
2. Scout cadence: 25 assessments vs a weekly timer. Default: assessments (activity-driven,
   matches the momentum model's philosophy).
3. Should `orphan_term` use the Stage 1b embedder to cluster near-synonym terms before
   counting? Default: no; whole-word counts first, measure noise.
