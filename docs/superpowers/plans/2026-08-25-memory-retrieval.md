# Memory & Retrieval Implementation Plan (Stage 1)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Under the Codex delegation protocol each task is one implementation brief.

**Spec:** [`../specs/2026-08-25-memory-retrieval.md`](../specs/2026-08-25-memory-retrieval.md)

**Goal:** One local retrieval layer (`engine/memory.py`) over the vault, fetched sources, probed papers, the learner's outputs, tutor turns, and generated questions. Agents ground on it and use it to avoid repeating themselves. Tasks 1–8 are FTS5/BM25 with the schema already shaped for vectors; Task 9 (Stage 1b) adds hybrid BM25 + vector ranking in the same PR series.

**Architecture:** A `Chunk` table (`context` header, `meta` JSON, `embedding_model`) + an FTS5 shadow table over `(context, text)` kept in sync by triggers + a `VaultLink` table from `[[wikilinks]]`. A `Retriever` protocol in `llm/` with `FtsRetriever` (fallback), `HybridRetriever` (default once Task 9 lands), and `ScriptedRetriever` (tests). One `retrieve()` function that filters in SQL, expands the query with concept aliases, ranks via the retriever, optionally orders by recency or expands 1 hop over vault links, dedups by hash, and emits an `AgentEvent`. Write sites call `index_text()` in the same transaction. Four callers inject `<<<MEMORY>>>` and `<<<ALREADY_COVERED>>>` blocks; three generators apply a code-level near-dup reject (Jaccard, then cosine in Task 9).

**Companion:** the traversable concept graph and the Scout are planned separately from `../specs/2026-08-25-concept-graph-and-scout.md`. They depend on Tasks 1–4 here.

**Tech Stack:** Python 3.12 · FastAPI · SQLModel · SQLite (WAL, FTS5, `PRAGMA foreign_keys=ON`) · Alembic · SvelteKit 5 (runes) · Tailwind 4 · pytest · vitest.

## Global Constraints

- **Zero live API and zero network in tests.** LLM via `ScriptedLLMClient`; retrieval via `ScriptedRetriever` or an in-memory SQLite with FTS5; `SourceDoc` fetch is injected.
- **Migrations are additive only.** `op.create_table` for `chunk` (inline `sa.ForeignKey` allowed on a new table). FTS5 table and triggers via `op.execute`. **Never** `batch_alter_table`. `down_revision = "d3b9f1c274ae"`.
- **Retrieval never blocks a caller.** Every retrieval path is wrapped: exception → `AgentEvent(kind="memory:error")` + empty result.
- **Prompts are version-tagged.** Bump the version of every prompt whose text changes (`TUTOR_BASE`, `PF_GENERATE`, `ROLEPLAY_DIRECTOR`, `PAPER_PROBE_DIRECTOR`, `RESEARCH_FOUNDATION`). Delimiters: `<<<MEMORY>>>`/`<<<END_MEMORY>>>`, `<<<ALREADY_COVERED>>>`/`<<<END_ALREADY_COVERED>>>`.
- **Constants live in code.** `DEFAULT_K = 6`, `INJECT_BUDGET_CHARS = 2400`, `CHUNK_TARGET_CHARS = 1200`, `MAX_INDEX_CHARS = 2_000_000`, `TUTOR_TURN_MIN_CHARS = 200`, `NEARDUP_JACCARD = 0.6` in `engine/memory.py`.
- **Both tutor paths.** `engine/tutor.py::run_tutor_turn` and `engine/tutor_sdk.py::run_tutor_turn_sdk` must share one helper for the memory blocks. No duplicated prompt assembly.
- **Ruff-clean.** No `;`-chained statements; no unused imports; add an import only in the task that uses it.
- **Backend tests:** `just test`. **Frontend tests:** `cd frontend && npx vitest run`.

---

### Task 1: `Chunk` model + FTS5 migration

**Files:**
- Modify: `src/adaptive_academy/models.py` (add `Chunk` after `SourceDoc`)
- Create: `alembic/versions/<rev>_memory_chunks.py`
- Modify: `src/adaptive_academy/db.py` (test-DB `create_all` path must also create `chunk_fts` + triggers; expose `ensure_fts(engine)`)
- Test: `tests/test_memory_models.py`, `tests/test_migration_memory.py`

**Interfaces:**
- `Chunk(id, kind, topic_id?, concept_id?, source_ref, ordinal, heading, text, context="", content_hash, meta: dict = {}, source_mtime?, embedding_model?, created_at)`; unique `(source_ref, ordinal)`; indexes `(kind, topic_id)`, `(kind, concept_id)`, `(source_ref)`, `(created_at)`. `meta` is `sa_column=Column(JSON)` like `Assessment.gaps`.
- `VaultLink(id, src_ref, dst_ref, dst_title)`; indexes `(src_ref)`, `(dst_ref)`.
- `db.ensure_fts(engine) -> bool` — creates `chunk_fts(context, text, content='chunk', content_rowid='id', tokenize='porter unicode61')` + 3 triggers if FTS5 is available; returns availability. Idempotent (`CREATE ... IF NOT EXISTS`).
- `db.FTS_DDL: list[str]` — the exact statements the migration also runs (single source).
- `db.ensure_vec(engine) -> bool` — stub in this task (returns `False`); Task 9 implements it.

- [ ] **Step 1: failing model test** — insert a `Chunk` with `topic_id`/`concept_id` FKs and a `meta` dict that round-trips; duplicate `(source_ref, ordinal)` raises `IntegrityError`; FK violation raises under `PRAGMA foreign_keys=ON`; `VaultLink` inserts and queries by `dst_ref`.
- [ ] **Step 2: failing migration test** — populated DB (topic, concept, assessment rows) → `alembic upgrade head`; assert `chunk`, `vaultlink`, `chunk_fts`, `chunk_ai`, `chunk_ad`, `chunk_au` exist; insert a `chunk` row via SQL with `context='Doc > Sec'` and `text='hello'`; `MATCH 'hello'` and `MATCH 'sec'` both return it; `alembic downgrade -1` drops all six.
- [ ] **Step 3: implement** models, `FTS_DDL`, `ensure_fts`, `ensure_vec` stub, migration (`upgrade` = two `create_table` + `for s in FTS_DDL: op.execute(s)`; `downgrade` = drop triggers, drop virtual table, drop both tables).
- [ ] **Step 4: wire tests' conftest** so every test engine calls `ensure_fts` after `create_all`.
- [ ] **Step 5:** `just test` green; `ruff check` clean.

**Acceptance:** both new test files pass; `uv run alembic upgrade head` on a copy of `adaptive_academy.db.bak-*` succeeds with foreign keys on.

---

### Task 2: Chunking + `index_text` (pure core)

**Files:**
- Create: `src/adaptive_academy/engine/memory.py`
- Test: `tests/test_memory_chunking.py`

**Interfaces:**
- `normalize(text) -> str` (collapse whitespace, strip, NFC).
- `content_hash(text) -> str` (sha256 hex of `normalize(text)`).
- `split_markdown(md, *, target=CHUNK_TARGET_CHARS) -> list[Piece]` where `Piece(heading: str, text: str, ordinal: int)`; split on `#`/`##`/`###`, then on paragraph boundaries when a section exceeds `target`; heading path joined with `" > "`; frontmatter stripped via `vault.parse_frontmatter`.
- `split_plain(text, *, target=CHUNK_TARGET_CHARS) -> list[Piece]` (paragraph splitter, heading `""`).
- `make_context(doc_title, heading_path) -> str` — `"{doc_title} > {heading_path}"`, or `doc_title` alone; this is the contextual header stored in `Chunk.context` and indexed by FTS.
- `extract_wikilinks(md) -> list[WikiLink(target: str, alias: str, heading: str)]` — handles `[[T]]`, `[[T|alias]]`, `[[T#H]]`, ignores code fences.
- `index_text(session, *, kind, text, source_ref, doc_title="", topic_id=None, concept_id=None, heading="", meta=None, source_mtime=None, splitter=None) -> IndexResult(indexed: int, skipped: int, removed: int)` — idempotent on `(source_ref, ordinal)`; unchanged hash → skipped; changed → update in place; fewer pieces than before → delete orphans with `ordinal >= len(pieces)`; sets `context` via `make_context`; stores `meta` on every piece. No commit inside; caller commits.
- `remove_source(session, source_ref) -> int`.
- `jaccard(a, b) -> float` over normalized token sets.

- [ ] **Step 1: failing tests** — heading split keeps path `"A > B"`; a 3,000-char section splits into ≥3 pieces on paragraph boundaries, never mid-word; frontmatter excluded; `context == "Doc > A > B"`; `meta` stored on every piece; `extract_wikilinks` parses all three forms and skips fenced code; `index_text` twice → second call `skipped == n`; edit one paragraph → `indexed == 1`; shorten a doc → `removed == k`; `jaccard("the cat sat", "the cat sat down") == 0.75`.
- [ ] **Step 2: implement** the pure functions and `index_text`.
- [ ] **Step 3:** tests green, ruff clean.

**Acceptance:** `tests/test_memory_chunking.py` passes; no LLM, no DB beyond `Chunk`.

---

### Task 3: `Retriever` seam + `retrieve()`

**Files:**
- Create: `src/adaptive_academy/llm/retriever_types.py`, `src/adaptive_academy/llm/fts_retriever.py`, `src/adaptive_academy/llm/scripted_retriever.py`
- Modify: `src/adaptive_academy/engine/memory.py` (add `retrieve`, `Hit`, `ChunkFilter`, `sanitize_fts_query`)
- Modify: `src/adaptive_academy/api/deps.py` (`get_retriever()`), `src/adaptive_academy/settings.py` (`retriever: str = "fts"`, env `AA_RETRIEVER`)
- Test: `tests/test_memory_fts.py`, `tests/test_memory_retrieve.py`

**Interfaces:**
- `ChunkFilter(kinds: tuple[str, ...], topic_id: int | None, concept_id: int | None, exclude_source_refs: tuple[str, ...])`.
- `Retriever` protocol: `name: str`; `search(session, query, *, where: ChunkFilter, k) -> list[tuple[int, float]]` (chunk id, score); `on_index(session, chunk_ids) -> None`.
- `FtsRetriever`: builds the filtered id set with SQL (concept filter admits `concept_id IS NULL` rows of the same topic), then `MATCH` + `bm25()` restricted to that set; scores normalized to 0..1 within the query.
- `ScriptedRetriever(hits: dict[str, list[int]] | None)`: if `hits` given, returns the scripted ids for a query; else ranks by token-overlap in Python. Both honor `where`.
- `sanitize_fts_query(q) -> str`: tokenize on non-alphanumerics, drop tokens < 2 chars, quote each, join with `OR`; empty → `'""'` guard returning no rows.
- `expand_query(session, query, *, concept_id) -> str` — appends the concept name and its `ConceptAlias.canonical_name` when present. Pure string work.
- `retrieve(session, retriever, query, *, kinds=(), topic_id=None, concept_id=None, k=DEFAULT_K, exclude_source_refs=(), order="relevance", since=None, expand_links=False, event_target: dict | None = None) -> list[Hit]`; `Hit(chunk, score, via: str = "direct" | "link")`; applies `expand_query`; `since` filters `created_at`; `order="recency"` takes top `3k` by score then sorts by `created_at` desc; `expand_links=True` adds, for each `vault_note` hit, the best-scoring chunk of each resolved `VaultLink.dst_ref` (1 hop) ranked below direct hits, total still ≤ `k`; dedups by `content_hash`; emits `AgentEvent(kind="memory:retrieve", detail="k=.. hits=.. links=.. kinds=.. order=.. ms=..")` with `event_target` keys (`conversation_id` | `topic_id` | `program_id`, and `roleplay_session_id`/`paper_probe_id` when given); wraps everything in try/except → `memory:error` + `[]`.
- `get_retriever()` resolves `settings.retriever` (`hybrid` default; `hybrid` degrades to `fts` until Task 9 lands or when the extra is missing; `fts` degrades to `ScriptedRetriever` when `ensure_fts` returned False). Logs the degradation once.

- [ ] **Step 1: failing FTS tests** — in-memory engine with FTS; insert/update/delete keep `chunk_fts` in sync; BM25 prefers the chunk with the exact term; a term present only in `context` still matches; `sanitize_fts_query('foo" OR 1=1 --')` yields a valid MATCH that returns rows for `foo` only; filters restrict by `kinds`, `topic_id`, `concept_id` (incl. NULL-concept admission), `exclude_source_refs`, `since`.
- [ ] **Step 2: failing retrieve tests** — dedup by hash; `k` cap; event emitted with the right FK; a retriever that raises → `[]` + `memory:error` event; `ScriptedRetriever` honors `where`; `order="recency"` returns newest first; `expand_query` appends the alias; `expand_links=True` adds a linked note's chunk with `via="link"` below direct hits and never exceeds `k`.
- [ ] **Step 3: implement** the three modules, `retrieve`, settings, deps.
- [ ] **Step 4:** tests green, ruff clean.

**Acceptance:** both test files pass with the default `fts` and with `AA_RETRIEVER=scripted`.

---

### Task 4: Vault full-text indexing + `SourceDoc` content indexing

**Files:**
- Modify: `src/adaptive_academy/engine/vault.py` (`ingest_vault` also indexes; add `reindex_vault`)
- Modify: `src/adaptive_academy/engine/memory.py` (add `index_source_doc`, `reindex_topic`)
- Modify: `src/adaptive_academy/engine/fetch.py` only if a `max_bytes` bump is needed for long sources (keep SSRF guard untouched)
- Modify: `src/adaptive_academy/api/deps.py` (`get_fetcher()`), `src/adaptive_academy/api/routes_topics.py` (accept hook at the `status = "accepted"` site), `src/adaptive_academy/api/routes_paper_probe.py` (`start_paper_probe` calls `index_paper`), `tests/conftest.py` (offline fetcher override)
- Test: `tests/test_memory_vault_ingest.py`, `tests/test_memory_source_doc.py`

Note: `fetch.fetch_artifact_text` returns `None` on failure (SSRF block, bad scheme, size, network) — it does not raise. `index_source_doc` treats `None`/empty as a skip (`memory:fetch_skipped`, no chunks) in addition to catching exceptions from an injected fetcher. Per-file vault read failures emit `memory:reindex_skipped` with the file URI; `reindex_topic` emits `memory:reindex_topic` (distinct from `reindex_vault`'s `memory:reindex`).

**Interfaces:**
- `vault.reindex_vault(session, topic_id, vault_path, *, subfolder="") -> IndexResult` — scans with `scan_notes` (export folder skipped), reads full text up to `MAX_INDEX_CHARS`, skips files whose `(mtime, hash)` match existing chunks, calls `index_text(kind="vault_note", source_ref=<file URI>, doc_title=note_title(...), meta={"tags": [...], "aliases": [...]} from frontmatter, splitter=split_markdown)`, removes chunks whose file is gone. Then rebuilds `VaultLink` rows for the file from `extract_wikilinks`, resolving targets against a title/alias → URI map built once per sweep (`vault.build_title_index(root)`). One commit per file. Emits `AgentEvent(kind="memory:reindex", detail=...)`.
- `memory.index_paper(session, pp: PaperProbe) -> IndexResult` — `kind="paper"`, `source_ref=f"paperprobe:{pp.id}"`, `doc_title=pp.paper_title`, `meta={"arxiv_id": <parsed from pp.paper_url or ""> , "url": pp.paper_url, "title": pp.paper_title}`, `splitter=split_markdown`, `topic_id` = the milestone's first topic when one exists. Called from `routes_paper_probe.start_paper_probe` after the probe row is flushed.
- `ingest_vault` calls `reindex_vault` after registering `SourceDoc`s (behavior otherwise unchanged; existing `test_api_vault.py` must still pass).
- `memory.index_source_doc(session, doc: SourceDoc, *, fetch=fetch_artifact_text) -> IndexResult` — fetches via the injected SSRF-guarded fetcher, `kind="source_doc"`, `source_ref=f"sourcedoc:{doc.id}"`, `heading=doc.title`. Fetch failure → `memory:fetch_skipped` event, no raise. Skips `file://` URLs whose chunks already exist as `vault_note` (vault-origin `SourceDoc`s).
- Hook: `api/routes_topics.py:239` (the only site that sets `SourceDoc.status = "accepted"`) calls `index_source_doc` for each newly accepted doc, with the injected fetcher from a new `deps.get_fetcher()` (defaults to `fetch.fetch_artifact_text`; tests override).
- `memory.reindex_topic(session, topic_id, *, vault_path, fetch, kinds=("vault_note", "source_doc"), deadline_s=60) -> ReindexResult(indexed, skipped, removed, truncated, ms)`.

- [ ] **Step 1: failing vault tests** — tmp vault with 3 notes that link to each other (one by alias, one unresolved): first reindex `indexed == total pieces`; `VaultLink` rows resolved by title and by frontmatter alias, unresolved link kept with `dst_ref == ""`; second reindex `skipped == total, indexed == 0`; touch + edit one file → only its chunks and links change; delete a file → its chunks and outgoing links removed; `Adaptive Academy/` folder skipped; non-UTF-8 file skipped and counted; `meta.tags` populated from frontmatter.
- [ ] **Step 2: failing source-doc + paper tests** — injected fetch returns text → chunks with `heading == title`; fetch raises → no chunks, `memory:fetch_skipped` event; vault-origin doc is not double-indexed; starting a paper probe (existing API test fixture) creates `paper` chunks with `meta.arxiv_id` parsed from an arXiv URL and `""` for pasted text.
- [ ] **Step 3: implement**.
- [ ] **Step 4:** `just test` green including `test_api_vault.py`.

**Acceptance:** re-running ingest on an unchanged vault indexes 0 chunks in < 2 s for 200 notes (assert on `skipped`, time budget as a soft check).

---

### Task 5: Write-site indexing (learner outputs, tutor turns, questions)

**Files:**
- Modify: `engine/tutor.py`, `engine/tutor_sdk.py`, `engine/assess.py` (`assess_concept`), `engine/teach.py` (`grade_teaching`), `engine/decay.py` (`schedule_decay_check`, `grade_decay_check`), `engine/productive_failure.py` (`generate_challenge`, `consolidate`), `engine/roleplay.py` (`run_roleplay_turn`, `direct`), `engine/paper_probe.py` (`direct`), `api/routes_paper_probe.py` (`post_answer`)
- Test: `tests/test_memory_write_sites.py`

**Interfaces:** one helper per site, all thin wrappers over `index_text`:
- `memory.index_message(session, msg: Message, *, concept_id, topic_id, levels: Levels | None = None)` — `role="user"` → `learner_output`; `role="tutor"` → `tutor_turn` only when `len(content) >= TUTOR_TURN_MIN_CHARS`, with `meta={"assistance": levels.assistance, "challenge": levels.challenge}`. `source_ref=f"message:{msg.id}"` (call after flush so `id` exists).
- `memory.index_assessment(session, a: Assessment, *, topic_id)` — `a.prompt` → `question` (`source_ref=f"assessment:{a.id}#q"`), `a.response` → `learner_output` (`#r`) with `meta={"assessment_kind": a.kind, "score": a.score, "verdict": a.verdict}`.
- `memory.index_roleplay_turn(session, t: RoleplayTurn, *, topic_id, concept_ids)`; `memory.index_question(session, *, text, source_ref, topic_id, concept_id)`; `memory.index_paper_answer(...)`.
- Topic resolution helper `memory.topic_id_for_concept(session, concept_id)` (reuse `productive_failure._topic_id_for` — promote it into `memory.py` and import from there).

**Known Task 6 tradeoff:** Roleplay and paper-probe grading index the same full transcript or QA text once per load-bearing concept. Hash dedup hides duplicates during retrieval, but these chunks still consume the `ALREADY_COVERED` candidate budget.

- [ ] **Step 1: failing tests** — for each site, drive the existing engine function with `ScriptedLLMClient` and assert the expected `Chunk` rows (`kind`, `source_ref`, `concept_id`) exist after the call; a 40-char tutor reply produces no `tutor_turn` chunk; re-running the same site does not duplicate.
- [ ] **Step 2: implement** the helpers and the one-line calls; keep every call inside the site's existing transaction.
- [ ] **Step 3:** full `just test` green — every pre-existing tutor/assess/roleplay/paper-probe test must pass unchanged.

**Acceptance:** `tests/test_memory_write_sites.py` passes; no existing test modified except to add fixtures.

---

### Task 6: Prompts + injection + near-dup reject

**Files:**
- Modify: `src/adaptive_academy/prompts.py` (bump `TUTOR_BASE`→v+1, `PF_GENERATE`→v3, `ROLEPLAY_DIRECTOR`→v2, `PAPER_PROBE_DIRECTOR`→v2, `RESEARCH_FOUNDATION`→v3; add `MEMORY_BLOCK_INTRO`, `ALREADY_COVERED_INTRO` text constants; `build_tutor_system_prompt(concept, levels, *, memory_block="", covered_block="")`)
- Modify: `src/adaptive_academy/engine/memory.py` (add `render_block(hits, *, marker, budget=INJECT_BUDGET_CHARS) -> str`, `memory_blocks_for_tutor(session, retriever, convo, concept, user_text) -> tuple[str, str, list[Hit]]`, `avoid_block_for_concepts(session, retriever, concept_ids, *, k=5) -> tuple[str, list[Hit]]`, `is_near_duplicate(text, hits, *, threshold=NEARDUP_JACCARD) -> Hit | None`)
- Modify: `engine/tutor.py`, `engine/tutor_sdk.py`, `engine/productive_failure.py`, `engine/roleplay.py`, `engine/paper_probe.py`, `engine/research.py`
- Modify: `api/deps.py` callers pass `retriever` (add `retriever: Retriever = Depends(get_retriever)` to the affected routes; engine functions take `retriever: Retriever | None = None`, `None` → skip blocks)
- Test: `tests/test_tutor_memory.py`, `tests/test_pf_neardup.py`, `tests/test_roleplay_memory.py`, `tests/test_paper_probe_memory.py`, `tests/test_research_memory.py`, `tests/test_prompts_memory.py`

**Behavior (from the spec's injection table):**
- Tutor: grounding = top-4 `vault_note`+`source_doc`+`paper` for the concept, query = `concept.name + " " + user_text`, `expand_links=True`; covered = top-3 `tutor_turn` + top-3 `learner_output` with `order="recency"`, `exclude_source_refs` = all `message:<id>` of the current conversation. `render_block` prints one provenance line per hit from `meta` (e.g. `[learner_output · self_explanation · score 0.4 · 2026-07-02]`, `[paper · arXiv:1706.03762 · § 3.2]`). `TurnResult` gains `memory: list[Hit]`.
- PF: grounding top-3; avoid top-5 `question`; after generation, `is_near_duplicate` → emit `memory:neardup_reject`, append rejected text to the covered block, regenerate once, accept the second result unconditionally.
- Roleplay `direct` / Paper-probe `direct`: avoid top-5 `question` across the milestone's concept ids; same reject rule (per question for paper probe; opening challenge for roleplay).
- Research: user message gains a `<<<ALREADY_COVERED>>>` list of vault note `heading`s for the topic; prompt text says "do not re-propose sources already in the learner's vault".
- Every block is `""` when there are no hits; markers are omitted entirely when empty.

- [ ] **Step 1: failing prompt tests** — each bumped prompt contains its new delimiter sentence; `.tag` reflects the new version; `render_block` truncates to budget on a chunk boundary and never cuts a chunk mid-way.
- [ ] **Step 2: failing tutor test** — seed a prior conversation's tutor turn for the concept and one message in the current conversation; run a turn with `ScriptedRetriever`; assert the system prompt sent to the scripted LLM contains the prior turn inside `<<<ALREADY_COVERED>>>` and does not contain the current conversation's message; `result.memory` is non-empty; `memory:retrieve` events present. Repeat for `run_tutor_turn_sdk` via its scripted path.
- [ ] **Step 3: failing PF test** — `ScriptedLLMClient` returns a near-duplicate of a seeded question first, a fresh one second; assert `memory:neardup_reject` event, second text persisted, exactly two `llm_call`s.
- [ ] **Step 4: failing roleplay / paper-probe / research tests** — avoid block present in the director user message; reject rule applied; research message lists vault headings.
- [ ] **Step 5: implement**.
- [ ] **Step 6:** `just test` green; existing prompt-snapshot tests updated only for the version bumps.

**Acceptance:** with `retriever=None` every engine function behaves exactly as before (regression tests unchanged). With a retriever, blocks appear and near-dups are rejected.

---

### Task 7: API (`routes_memory.py`) + turn response field

**Files:**
- Create: `src/adaptive_academy/api/routes_memory.py`
- Modify: `src/adaptive_academy/api/schemas.py` (`MemoryHitOut`, `MemorySearchOut`, `MemoryReindexIn/Out`, `MemoryStatsOut`; `SendMessageOut.memory: list[MemoryHitOut] = []`), `api/app.py` (include router), `api/routes_conversations.py` (populate `memory`)
- Test: `tests/test_api_memory.py`, extend `tests/test_api_conversations.py`

**Endpoints:**
- `GET /api/memory/search?q=&topic_id=&concept_id=&kinds=&k=` → `MemorySearchOut(hits=[{chunk_id, kind, heading, snippet(≤240 chars), score, source_ref}])`; `q` required, 400 when blank.
- `POST /api/memory/reindex` `{topic_id?, vault_path?, kinds?}` → `{indexed, skipped, removed, truncated, ms}`; `vault_path` resolved like `routes_vault._resolve_path`; `topic_id` omitted → all topics.
- `GET /api/memory/stats?topic_id=` → `{by_kind: {kind: count}, last_indexed_at, retriever}`.

- [ ] **Step 1: failing API tests** — search returns ranked hits with snippets; blank `q` → 400; reindex on a tmp vault returns counts and is idempotent; stats counts match; `send_message` response carries `memory` entries when the scripted retriever has hits and `[]` otherwise.
- [ ] **Step 2: implement**.
- [ ] **Step 3:** `just test` green.

---

### Task 8: Frontend — "What it remembered" + vault search/reindex

**Files:**
- Modify: `frontend/src/lib/types.ts` (`MemoryHit`, extend `SendMessageOut`), `frontend/src/lib/api.ts` (`searchMemory`, `reindexMemory`, `memoryStats`)
- Create: `frontend/src/lib/ui/MemoryDisclosure.svelte`
- Modify: `frontend/src/routes/topics/[id]/tutor/+page.svelte` (render `MemoryDisclosure` under each tutor reply), `frontend/src/routes/topics/[id]/vault/+page.svelte` (search input + results grouped by kind + Reindex button with counts toast)
- Test: `frontend/src/lib/memory.test.ts` (pure helpers: group-by-kind, snippet trim), `frontend/src/lib/ui/MemoryDisclosure.test.ts`

- [ ] **Step 1: failing vitest** — `MemoryDisclosure` renders collapsed with "What it remembered (n)"; expanding lists kind badge + heading + snippet; renders nothing when `hits` is empty; `groupByKind` helper orders `vault_note, source_doc, learner_output, tutor_turn, question`.
- [ ] **Step 2: implement** with existing `Badge`, `Card`, `Button`, `Input` from `$lib/ui`; match the `EventFeed` collapsed-row styling.
- [ ] **Step 3:** `npx vitest run` green; `npm run check` clean.

---

### Task 9 (Stage 1b): Hybrid BM25 + vector retriever

**Files:**
- Modify: `pyproject.toml` (`[project.optional-dependencies] memory = ["sqlite-vec>=0.1.9", "fastembed>=0.3"]`), `Dockerfile` (install the extra), `README.md` (one-time model download note)
- Create: `src/adaptive_academy/llm/embedder_types.py`, `llm/onnx_embedder.py`, `llm/scripted_embedder.py`, `llm/hybrid_retriever.py`
- Modify: `src/adaptive_academy/db.py` (`ensure_vec` real implementation: `sqlite_vec.load(conn)` on connect via an engine event, `CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[384])`), `engine/memory.py` (embed on index; `is_near_duplicate` gains cosine), `api/deps.py` (`get_embedder`, `hybrid` resolution), `settings.py` (`embedding_model: str = "BAAI/bge-small-en-v1.5"`)
- Test: `tests/test_hybrid_retriever.py`, `tests/test_memory_embed_on_index.py`

**Interfaces:**
- `Embedder` protocol: `name: str`; `dim: int`; `embed(texts: list[str]) -> list[list[float]]`.
- `ScriptedEmbedder(dim=384)` — deterministic hashed bag-of-words, L2-normalized. Test default.
- `OnnxEmbedder(model=settings.embedding_model)` — `fastembed.TextEmbedding`; lazy model load; import guarded.
- `HybridRetriever(fts: FtsRetriever, embedder: Embedder)` — `search` runs FTS top-20 and `chunk_vec` KNN top-20 (both restricted to the pre-filtered id set), fuses with reciprocal-rank fusion (`k=60`), returns top-`k`; `on_index(chunk_ids)` embeds `context + "\n" + text` in one batch and upserts `chunk_vec`, sets `Chunk.embedding_model`.
- `index_text` calls `retriever.on_index(new_or_changed_ids)` when a retriever is passed; `reindex` re-embeds rows whose `embedding_model != embedder.name`.
- `is_near_duplicate` → Jaccard ≥ 0.6 **or** cosine ≥ 0.86 (cosine only when an embedder is available).

- [ ] **Step 1: failing tests** — with `ScriptedEmbedder` and `sqlite-vec` loaded (skip the module if the extension is unavailable): a query that matches one chunk by exact term and another only semantically (scripted vectors engineered to be close) returns both, RRF order deterministic; filters still apply; a chunk with stale `embedding_model` is re-embedded on reindex; `chunk_vec` row count equals embedded chunk count after delete; `is_near_duplicate` triggers on cosine alone.
- [ ] **Step 2: implement**; keep every new import behind `try/except ImportError` so `just test` passes on a host without the extra.
- [ ] **Step 3:** `just test` green with and without the extra installed (`uv sync --extra memory` vs plain); `AA_RETRIEVER` unset → `hybrid` when available, else `fts`, logged once.

**Acceptance:** `/api/memory/stats` reports `retriever: "hybrid"` in the container; on a host without the extra it reports `"fts"` and nothing else changes.

---

## Final verification (after all tasks)

- [ ] `just test` green; `cd frontend && npx vitest run` green; `ruff check` clean; `npm run check` clean.
- [ ] `uv run alembic upgrade head` against a copy of the real DB with `PRAGMA foreign_keys=ON`; then `POST /api/memory/reindex` with the real vault path; record `indexed` and `ms` in the PR description.
- [ ] Manual: one tutor turn on a concept with prior history shows a non-empty "What it remembered"; the reply does not restate the prior explanation (read it).
- [ ] Manual: generate two PF challenges on one concept; the second differs (check `memory:neardup_reject` in the event feed if the model repeated).
- [ ] Container: rebuild image with the `memory` extra; `AA_RETRIEVER` unset → `hybrid`; `/api/memory/stats` reports `retriever: "hybrid"`. Host dev without the extra reports `"fts"`.
- [ ] Manual: search the vault page for a term that appears only in a linked note's title; the linked note appears with `via: link`.
- [ ] Update `docs/OVERVIEW.md` architecture block (`engine/ … memory`) and `README.md` "What it does" with one line on retrieval + "What it remembered" + the one-time embedding-model download.
- [ ] Memory note: new `Assessment`-adjacent write sites must call `index_*`; add to the lesson list alongside the `ARTIFACT_KINDS`/`QUALIFYING_KINDS` rule.

## Next (separate plan, not started)

`ConceptEdge` (bi-temporal), `chunk_concept`, graph-aware remediation and retrieval expansion, and the topic Scout — see `../specs/2026-08-25-concept-graph-and-scout.md`. Depends on Tasks 1–4 of this plan.
