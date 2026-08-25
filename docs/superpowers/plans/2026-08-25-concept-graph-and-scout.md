# Concept Graph & Scout Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Under the Codex delegation protocol each task is one implementation brief.

**Spec:** [`../specs/2026-08-25-concept-graph-and-scout.md`](../specs/2026-08-25-concept-graph-and-scout.md)
**Depends on:** memory-retrieval plan Tasks 1–4 (`Chunk`, `index_text`, `retrieve`, vault/paper indexing). Run this plan after those land on the branch.

**Goal:** Materialize the concept graph as a bi-temporal `ConceptEdge` table traversed by recursive CTE; link chunks to concepts (`ChunkConcept`); use the graph in remediation, the map, and retrieval; add a Scout that proposes new topics from evidence as reviewable `TopicSuggestion` rows.

**Architecture:** Three new tables, one migration. `engine/graph.py` owns population and traversal (pure SQL, no LLM). `engine/scout.py` owns four deterministic candidate generators and one structured-output ranking call. Accept routes through the existing `ProgramTopicLink` stub path. No graph database, no entity extraction.

**Tech Stack:** Python 3.12 · FastAPI · SQLModel · SQLite (recursive CTE, `PRAGMA foreign_keys=ON`) · Alembic · SvelteKit 5 (runes) · Tailwind 4 · pytest · vitest.

## Global Constraints

- **Zero live API in tests.** LLM via `ScriptedLLMClient`; retrieval via `ScriptedRetriever`.
- **Migrations are additive only.** Three `op.create_table`s with inline FKs (new tables). No `ALTER` on existing tables. **Never** `batch_alter_table`. `down_revision` = the memory-retrieval revision id.
- **Edges are never deleted.** Invalidate with `valid_until = now`. The only `DELETE` on `conceptedge` is in the migration downgrade.
- **Graph never passes a gate.** `gates.py` is not modified.
- **Traversal depth is capped at 6** in code; default 3.
- **Scout never creates a topic or milestone.** Accept creates a `ProgramTopicLink` stub only.
- **Prompts are version-tagged.** New `SCOUT_RANK` v1; `REMEDIATE` bumps one version for the ancestor sentence.
- **Ruff-clean.** No `;`-chained statements; no unused imports.
- **Backend tests:** `just test`. **Frontend tests:** `cd frontend && npx vitest run`.

---

### Task 1: Models + migration

**Files:**
- Modify: `src/adaptive_academy/models.py` (add `ConceptEdge`, `ChunkConcept`, `TopicSuggestion` after `MapChange`)
- Create: `alembic/versions/<rev>_concept_graph_tables.py`
- Test: `tests/test_graph_models.py`, `tests/test_migration_graph.py`

**Interfaces:**
- `ConceptEdge(id, src_concept_id, dst_concept_id, kind, weight=1.0, origin, origin_ref="", valid_from, valid_until?, recorded_at)`; indexes `(src_concept_id, valid_until)`, `(dst_concept_id, valid_until)`.
- `ChunkConcept(id, chunk_id, concept_id, hits=1)`; unique `(chunk_id, concept_id)`.
- `TopicSuggestion(id, program_id?, title, rationale, candidate_kind, evidence: list[dict], score, status="proposed", created_at, decided_at?)`; index `(status, program_id)`.

- [ ] **Step 1: failing model tests** — insert an edge between two concepts; FK violation raises under `PRAGMA foreign_keys=ON`; duplicate `(chunk_id, concept_id)` raises; `TopicSuggestion.evidence` round-trips a list of dicts.
- [ ] **Step 2: failing migration test** — populated DB → `alembic upgrade head`; three tables + indexes exist; `downgrade -1` drops them.
- [ ] **Step 3: implement.**
- [ ] **Step 4:** `just test` green; ruff clean.

---

### Task 2: `engine/graph.py` — population + traversal (pure)

**Files:**
- Create: `src/adaptive_academy/engine/graph.py`
- Test: `tests/test_graph_edges.py`, `tests/test_graph_traversal.py`

**Interfaces:**
- `resolve_concept(name, concepts: list[Concept]) -> Concept | None` — exact, then `aliases.normalize_name` match.
- `edges_from_prerequisite_map(prerequisite_map: dict, concepts: list[Concept]) -> tuple[list[tuple[int, int]], list[str]]` — `(src, dst)` pairs where `src` requires `dst`; unresolved names returned, never invented.
- `invalidate_track_edges(session, track_id, *, origin="researcher", now=None) -> int` — sets `valid_until` on current edges whose `src` is in the track and `origin` matches.
- `insert_edges(session, pairs, *, kind, origin, origin_ref="", weight=1.0) -> int` — skips pairs that already have a current edge with the same `(src, dst, kind)`.
- `alias_edges(session, program_id, canonical_name) -> int` — both directions inside the group; idempotent.
- `invalidate_concept_edges(session, concept_ids, *, now=None) -> int` — any current edge touching the ids.
- `ancestors(session, concept_id, *, kind="prerequisite", max_depth=3, at=None) -> list[tuple[int, int]]`; `descendants(...)`; `neighbors(session, concept_id, *, kinds=(...), at=None) -> list[int]` — one recursive CTE each, `UNION` (not `UNION ALL`) for cycle safety, `max_depth` clamped to 6, validity predicate `valid_until IS NULL` or the `at` window.
- `weakest_ancestor(session, concept_id) -> tuple[int, float] | None` — ancestors ordered by `KnowledgeEstimate.level` (`low < medium < high`), then latest `Assessment.score`; returns `(concept_id, score_or_0)`.
- `frontier(session, track_id) -> list[tuple[int, list[str]]]` — concepts whose `gates.evaluate_concept` passes and that have ≥ 1 current neighbor whose concept belongs to no `Track` with a `Topic` (use `neighbors` then filter); returns `(concept_id, [outside neighbor names])`.
- `backfill(session) -> BackfillResult(tracks: int, edges: int, unresolved: int)` — for every `TopicFoundation` with a `Track`, invalidate + insert researcher edges; for every alias group, alias edges. Idempotent.

- [ ] **Step 1: failing edge tests** — fixture `prerequisite_map` with an exact name, a case/punctuation variant, and an unknown name → two edges + one unresolved; `insert_edges` twice inserts once; `invalidate_track_edges` sets `valid_until` and a re-insert creates a *new* row (old row kept); alias group of three concepts → six edges, idempotent; `backfill` twice → same counts.
- [ ] **Step 2: failing traversal tests** — 6-node fixture with a cycle: `ancestors` depth 1/2/3 sets; depth 10 clamps to 6 and terminates; invalidated edge excluded by default, included with `at=` before invalidation; `neighbors` honors `kinds`; `weakest_ancestor` picks the `low` node over a `medium` node with a lower score; `frontier` returns the solid concept with an out-of-track neighbor and not the unsolid one.
- [ ] **Step 3: implement.**
- [ ] **Step 4:** tests green; ruff clean.

---

### Task 3: Population hooks (curriculum, aliases, revision) + `just graph-backfill`

**Files:**
- Modify: `src/adaptive_academy/engine/curriculum.py` (after `Concept` rows are created and committed), `engine/aliases.py` (`apply_program_aliases`, after registering), `engine/revision.py` (`apply_change`, `prune_topic` branch), `src/adaptive_academy/cli.py` (`graph-backfill` command), `justfile`
- Test: `tests/test_graph_population.py`, `tests/test_revision_edges.py`, extend `tests/test_curriculum_orchestrator.py` and `tests/test_aliases.py` with one assertion each

- [ ] **Step 1: failing tests** — generating a curriculum for a topic with a 3-concept `prerequisite_map` creates 2 current `researcher` edges and one `AgentEvent(kind="graph:edges", detail="2 edges, 1 unresolved")`; regenerating invalidates the old two and inserts anew; `apply_program_aliases` on a second topic sharing a concept name creates alias edges both ways; accepting a `prune_topic` change invalidates every edge touching that topic's concepts and emits `graph:invalidate`; rejecting touches nothing.
- [ ] **Step 2: implement** the three hooks (each ≤ 10 lines calling `graph.*`), the CLI command, the `just` recipe.
- [ ] **Step 3:** `just test` green; every pre-existing curriculum/alias/revision test unchanged.

---

### Task 4: `ChunkConcept` tagging inside `index_text`

**Files:**
- Modify: `src/adaptive_academy/engine/memory.py` (`index_text` tags after upsert; `tag_chunk_concepts(session, chunk, names: list[tuple[int, str]]) -> int`; `concept_name_index(session, topic_id) -> list[tuple[int, str]]` cached per call)
- Modify: `engine/graph.py` (`expand_query` neighbor names — or place in `memory.expand_query`, calling `graph.neighbors`)
- Test: `tests/test_chunk_concept.py`, extend `tests/test_memory_retrieve.py` (neighbor expansion)

- [ ] **Step 1: failing tests** — index a chunk mentioning two concept names (one via alias canonical name) → two `ChunkConcept` rows with `hits`; a 3-char concept name is skipped; whole-word only (`attention` does not match `attentional`); re-index with changed text updates rows; `expand_query` appends up to 3 neighbor names after the alias.
- [ ] **Step 2: implement.**
- [ ] **Step 3:** `just test` green.

---

### Task 5: Graph uses — remediation, map API, `/map` page

**Files:**
- Modify: `src/adaptive_academy/engine/remediate.py` (`remediate_concept`: call `graph.weakest_ancestor`; when its level is lower than the target's, pass `ancestor_name` to `build_remediate_prompt`, choose the ancestor's earliest phase as target, emit `remediate:ancestor`), `prompts.py` (`REMEDIATE` v+1 with an optional `ANCESTOR:` line)
- Create: `src/adaptive_academy/api/routes_graph.py` (`GET /api/topics/{id}/graph`, `GET /api/concepts/{id}/ancestors?depth=`, `GET /api/concepts/{id}/neighbors`), schemas `GraphOut(nodes, edges)`, `EdgeOut(src, dst, kind, weight)`
- Modify: `api/app.py` (include router), `frontend/src/lib/api.ts` (`getGraph`), `frontend/src/lib/types.ts`, `frontend/src/routes/topics/[id]/map/+page.svelte` (edges from `getGraph`; remove client-side name matching; legend; ancestor highlight on select via `getAncestors`)
- Test: `tests/test_remediate_ancestor.py`, `tests/test_api_graph.py`, `frontend/src/lib/graph.test.ts` (pure helper: edge → link mapping, legend labels)

- [ ] **Step 1: failing tests** — remediation with a `low` ancestor targets the ancestor's phase and the prompt contains `ANCESTOR:`; with no weaker ancestor behavior is unchanged; `GET /graph` returns nodes + current edges only; `ancestors?depth=2` respects depth; unknown concept → 404.
- [ ] **Step 2: implement.**
- [ ] **Step 3:** `just test` and `npx vitest run` green; `npm run check` clean.

---

### Task 6: Scout candidates (pure) + ranking + persistence

**Files:**
- Create: `src/adaptive_academy/engine/scout.py`
- Modify: `prompts.py` (`SCOUT_RANK` v1 with `<<<CANDIDATES>>>`/`<<<END_CANDIDATES>>>` delimiters and a "cite evidence indexes; drop anything without evidence" instruction), `llm/structured.py` schema `SCOUT_SCHEMA` (items ≤ 5)
- Test: `tests/test_scout_candidates.py`, `tests/test_scout_rank.py`

**Interfaces:**
- `Candidate(kind, label, evidence: list[dict], weight: float)`.
- `frontier_candidates(session, program_id) -> list[Candidate]` (via `graph.frontier` per track in the program).
- `orphan_term_candidates(session, program_id) -> list[Candidate]` — over `learner_output` + `tutor_turn` chunks for the program's topics; term extractor = capitalized multi-word runs + backticked identifiers; drop terms matching any concept/alias name (whole-word); keep `count >= 3` across `>= 2` distinct `source_ref`s.
- `orphan_note_candidates(session) -> list[Candidate]` — `vault_note` chunks grouped by `source_ref` with zero `ChunkConcept` rows.
- `extension_candidates(session, program_id) -> list[Candidate]` — chunks with `meta.role == "extension"`.
- `build_digest(candidates, program, milestones, *, max_chars=12_000) -> tuple[str, list[Candidate]]` — indexed list; truncates lowest-weight first and logs the drop count.
- `rank(session, program, candidates, *, llm) -> list[TopicSuggestion]` — one `structured_json` call; validates `evidence_indexes` ⊂ digest indexes; drops items with none; upserts by `normalize_name(title)`; skips titles dismissed within `SCOUT_DISMISS_COOLDOWN_DAYS = 30`; emits `AgentEvent(program_id, kind="scout:ranked", detail=...)`.
- `run_scout(session, program, *, llm, deadline_s=10) -> ScoutResult(suggestions, counts: dict[str, int], truncated: bool)`.
- `maybe_scout(session, program_id, *, llm)` — counts `Assessment` rows for the program since the last `scout:ranked` event; runs when `>= SCOUT_EVERY_N_ASSESSMENTS (25)`.

- [ ] **Step 1: failing candidate tests** — each generator on a fixture: frontier finds the solid concept with an outside neighbor; orphan terms require 3 mentions across 2 sources and exclude concept names; orphan notes exclude tagged notes; extension picks `meta.role`; `build_digest` truncates and reports the count.
- [ ] **Step 2: failing rank tests** — `ScriptedLLMClient` returns 6 items, one without evidence → 5 stored with evidence refs resolved; second run with the same titles upserts (no duplicates); a title dismissed yesterday is not re-proposed; `maybe_scout` fires at 25 and not at 24.
- [ ] **Step 3: implement.**
- [ ] **Step 4:** `just test` green.

---

### Task 7: Scout API + accept/dismiss + dashboard/program UI

**Files:**
- Create: `src/adaptive_academy/api/routes_scout.py` (`POST /api/programs/{id}/scout`, `GET /api/programs/{id}/suggestions?status=`, `POST /api/suggestions/{id}/accept` body `{milestone_id}`, `POST /api/suggestions/{id}/dismiss`), schemas `TopicSuggestionOut`, `ScoutOut`
- Modify: `api/app.py`, `api/routes_assess.py` (call `scout.maybe_scout` after a successful assessment when the concept's topic is in a program; wrapped so a scout failure never fails the assessment), `frontend/src/lib/api.ts`, `types.ts`, `frontend/src/routes/+page.svelte` (a "Scout found N" card, collapsed when 0), `frontend/src/routes/programs/[id]/+page.svelte` (suggestions list with milestone picker on accept, dismiss, evidence popover, "Run scout" button)
- Test: `tests/test_api_scout.py`, extend `tests/test_api_assess.py` (assessment still succeeds when scout raises), `frontend/src/lib/scout.test.ts` (evidence label formatting; grouping by kind), a vitest for the card

- [ ] **Step 1: failing API tests** — scout run returns suggestions + counts; accept creates a `ProgramTopicLink(status="stub", added_by="scout")` under the given milestone and marks the suggestion accepted with `decided_at`; accept without a valid milestone → 400; dismiss marks dismissed; accepting twice → 409; assessment route unaffected by a scout exception.
- [ ] **Step 2: implement.**
- [ ] **Step 3:** `just test` and `npx vitest run` green; `npm run check` clean.

---

## Final verification (after all tasks)

- [ ] `just test` green; `cd frontend && npx vitest run` green; `ruff check` clean; `npm run check` clean.
- [ ] `uv run alembic upgrade head` on a copy of the real DB with foreign keys on; then `just graph-backfill`; record edge/unresolved counts in the PR.
- [ ] Manual: `/map` shows server edges; selecting a concept highlights its ancestors.
- [ ] Manual: run scout on the real program; read the five suggestions and their evidence; accept one; it appears as a stub on the Program page.
- [ ] Update `docs/OVERVIEW.md` (`engine/ … graph · scout`) and `README.md` "What it does" (one line each for the graph and the Scout).
- [ ] Memory note: curriculum regeneration must go through `graph.invalidate_track_edges` + `insert_edges`; never delete edges.
