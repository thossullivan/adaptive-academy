---
title: Memory & Retrieval — one local index over the vault, sources, and the learner's own record
created: 2026-08-25
status: approved for planning
companion_to:
  - 2026-06-17-obsidian-vault-integration.md
  - 2026-06-15-adaptive-academy-redesign.md
  - 2026-07-15-paper-probe-design.md
  - 2026-07-15-roleplay-examiner-design.md
---

# Memory & Retrieval

**Status:** Approved for planning.

## Goal

Add one **local retrieval layer** that every agent can query at call time. It indexes four
things the app already has but cannot search: the Obsidian vault (full text, not a
280-character summary), fetched `SourceDoc` content, the learner's own outputs
(`Assessment.response`, teach-backs, roleplay and probe transcripts), and the Tutor's own
prior explanations. Two outcomes follow:

1. **Grounded generation.** The Tutor, the productive-failure generator, the roleplay
   director, and the paper-probe director receive the top-k relevant chunks from *your*
   corpus, not only the model's priors.
2. **No repetition.** Before an agent explains or asks, it sees what it already explained or
   asked for this concept, and what you already wrote. The prompt says: *build on this, do
   not restate it.* Near-duplicate questions are rejected in code.

## Why

Today `ingest_vault` registers a note as a `SourceDoc` with a title and a 280-char summary.
No agent reads vault content at call time; only `research.py` and `curriculum.py` consume
`SourceDoc` rows, and only as a reading list. The Tutor's system prompt is
`TUTOR_BASE.format(concept, assistance, challenge)` — no corpus, no history beyond the
current conversation. Nothing checks what the learner already produced. Question dedup
exists only for anchors (`anchors.anchor_key`, exact match after whitespace collapse).

The result: the Tutor re-explains from scratch, practice generators re-ask near-identical
problems, and the vault you already maintain is dead weight at retrieval time. A tool
whose thesis is *durable, unassisted, delayed performance* should know what you have and
have not already done.

**Why not Honcho / a hosted memory service.** Honcho models the *user* and runs hosted (or
self-hosted on Postgres + pgvector). Both conflict with this repo's commitments: records
stay local; SQLite is the single source of truth; the `Assessment` spine *is* the user model.
A second user model would compete with the competence triangulation. What is missing is a
*document/record index*, and that belongs in-process.

**Why the vault is the corpus.** `basic-memory` already writes Obsidian-compatible markdown
into the same vault. One folder tree serves Claude Code sessions and the app. The app reads
the files directly; it never depends on the basic-memory MCP server or its private index.

## Scope

**In:** a `Chunk` table (with a portable `meta` JSON column) plus an FTS5 index (SQLite
BM25); full-text vault ingest with heading-level chunking, contextual chunk headers, and
incremental re-index; a `vault_link` table built from `[[wikilinks]]` for 1-hop expansion;
indexing of learner outputs, tutor turns, generated questions, probed paper text, and
fetched `SourceDoc` text; one `retrieve()` function with relevance/recency ordering and
alias-expanded queries; a `Retriever` seam in `llm/` with a scripted implementation;
**hybrid BM25 + vector ranking (Stage 1b)** via `sqlite-vec` and a local ONNX embedder,
with FTS5-only as the automatic fallback; Tutor grounding + "already covered" injection;
question avoid-lists in three generators plus a code-level near-dup reject; `AgentEvent`
tracing per retrieval; a `/api/memory/search` endpoint and a small "What it remembered"
disclosure in the tutor UI; migrations; tests.

**Companion spec:** the traversable concept graph (`ConceptEdge`, bi-temporal) and the
topic Scout live in `2026-08-25-concept-graph-and-scout.md`. That spec depends on this one.

**Out (deferred):** a user-model / dialectic layer (Honcho/Mem0/Zep — see § Why); an
LLM-extracted entity graph (GraphRAG/LightRAG — see § Architecture); a graph database
(Neo4j/LadybugDB — see companion spec); PDF parsing; re-ranking with an LLM or a
cross-encoder; LLM-generated contextual chunk summaries (behind a flag, papers only, later);
re-indexing the vault on a file watcher (manual/API trigger + on-demand staleness check
only); chunk-level UI browsing beyond the search endpoint; multi-user.

## Architecture

Chosen approach: **one table, one virtual FTS5 index, one function.** Retrieval is a pure
engine capability (`engine/memory.py`) with no LLM in the loop. Callers pass a query string
and filters and receive ranked `Chunk` rows. The ranking backend sits behind a `Retriever`
protocol in `llm/` so tests use a deterministic scripted implementation and Stage 1b can add
vectors without touching callers.

Rejected alternatives:

- **External vector DB (Chroma/LanceDB/Qdrant).** Adds a daemon or a second storage engine.
  Breaks "backup = copy one file."
- **Embeddings-only.** Anthropic offers no embeddings API; any hosted embedder ships
  corpus content off-machine on every index pass. A local ONNX embedder is the only
  local-first option. Hybrid BM25 + vector is the 2026 baseline, not an upgrade:
  Anthropic's contextual-retrieval data shows contextual BM25 + embeddings cut top-20
  retrieval failures by 49% versus embeddings alone. So FTS5 ships first (zero deps, the
  fallback) and vectors follow in the same PR series (Stage 1b), never as a separate era.
- **LLM-extracted entity graph (GraphRAG / LightRAG).** The 2026 RAGSearch benchmark finds
  agentic multi-round retrieval narrows the gap to GraphRAG except on complex multi-hop
  questions, and only when the offline extraction cost is amortized. This corpus is small,
  and the concept graph is already curated by the CurriculumDirector; an extracted graph
  would be noisier and cost tokens on every reindex.
- **Hosted / server memory layers (Honcho, Mem0, Zep/Graphiti).** Graphiti requires Neo4j,
  FalkorDB, or Neptune and defaults to OpenAI embeddings; Mem0 and Honcho model the user.
  All solve multi-tenant, multi-agent memory. This is single-user, single-machine. One idea
  is borrowed: bi-temporal edges (companion spec).
- **Store chunks as markdown in the vault instead of SQLite.** The vault is a *source*, not
  the store. The app already guards against its own export feedback loop; indexing its own
  exports as ground truth would re-open that loop.

**Deliberate divergence from the "no SQLite-only SQL" discipline** in the redesign spec:
FTS5 virtual tables are SQLite-only. The redesign spec already blesses `sqlite-vec` for this
exact need. The divergence is confined to `engine/memory.py` and one migration; the
`Chunk` table itself is portable, and a Postgres port would swap the FTS5 module for
`tsvector` behind the same `Retriever` seam.

## Components

- `engine/memory.py` — chunking, hashing, index maintenance, `retrieve()`, injection
  helpers, near-dup reject.
- `llm/retriever_types.py` — `Retriever` protocol + `Hit` dataclass.
- `llm/fts_retriever.py` — FTS5/BM25 implementation (Stage 1 default).
- `llm/scripted_retriever.py` — deterministic in-memory implementation for tests.
- `llm/hybrid_retriever.py` + `llm/embedder_types.py` + `llm/onnx_embedder.py` +
  `llm/scripted_embedder.py` — Stage 1b.
- `api/routes_memory.py` — search + reindex endpoints.
- `api/deps.py::get_retriever()` — registry resolution (`AA_RETRIEVER=fts|scripted|vec`).
- `prompts.py` — new delimited blocks: `<<<MEMORY>>>`/`<<<END_MEMORY>>>` (grounding) and
  `<<<ALREADY_COVERED>>>`/`<<<END_ALREADY_COVERED>>>` (anti-repeat); bump the versions of
  `TUTOR_BASE`, `PF_GENERATE`, `ROLEPLAY_DIRECTOR`, `PAPER_PROBE_DIRECTOR`.
- Frontend: `MemoryDisclosure.svelte` under the tutor page; a search box on the vault page.

## Data Model

```python
class Chunk(SQLModel, table=True):
    """One indexed span of text. The unit of retrieval and of dedup."""
    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str            # vault_note | source_doc | learner_output | tutor_turn | question
    topic_id: Optional[int] = Field(default=None, foreign_key="topic.id")
    concept_id: Optional[int] = Field(default=None, foreign_key="concept.id")
    source_ref: str      # file URI (vault_note) | "sourcedoc:<id>" | "assessment:<id>" |
                         # "message:<id>" | "roleplayturn:<id>" | "paperprobe:<id>#<qi>" | ...
    ordinal: int = 0     # position within the source (heading order / paragraph index)
    heading: str = ""    # nearest markdown heading path, "A > B > C"
    text: str            # body text as written
    context: str = ""    # contextual header prepended at index time: "<doc title> > <heading path>"
    content_hash: str    # sha256 of normalized text — dedup + staleness
    meta: dict = Field(default_factory=dict, sa_column=Column(JSON))
                         # portable json1 ⇄ jsonb. Citation + provenance, by kind:
                         #  paper/source_doc: arxiv_id, authors, year, url, section
                         #  tutor_turn: assistance, challenge
                         #  learner_output: assessment_kind, score, verdict
                         #  vault_note: tags, aliases (from frontmatter)
    source_mtime: Optional[float] = None   # vault files only
    embedding_model: Optional[str] = None  # set when chunk_vec holds a row (Stage 1b)
    created_at: datetime = Field(default_factory=_now)


class VaultLink(SQLModel, table=True):
    """One [[wikilink]] from a vault note to another, extracted at index time."""
    id: Optional[int] = Field(default=None, primary_key=True)
    src_ref: str          # file URI of the linking note
    dst_ref: str          # file URI of the target note (resolved by title/alias; "" if unresolved)
    dst_title: str        # raw link text, for unresolved links
```

Indexes: `(kind, topic_id)`, `(kind, concept_id)`, `(source_ref)`, `(created_at)`, unique
`(source_ref, ordinal)`; `vaultlink(src_ref)`, `vaultlink(dst_ref)`.

The FTS5 table indexes `context` and `text` together so the heading path contributes to
BM25 — the no-LLM form of contextual retrieval. `meta` is never indexed for search; it is
returned with hits so the injected block can cite ("*you scored 0.4 on this on 2026-07-02*",
"*Vaswani et al. 2017 § 3.2*").

FTS5 shadow table (created in the migration with `op.execute`; not a SQLModel):

```sql
CREATE VIRTUAL TABLE chunk_fts USING fts5(
  context, text, content='chunk', content_rowid='id', tokenize='porter unicode61');
-- AFTER INSERT / AFTER DELETE / AFTER UPDATE triggers keep chunk_fts in sync.
```

Stage 1b adds `chunk_vec` (`sqlite-vec`, `vec0`, `embedding float[384]`) keyed by
`chunk.id`, created only when the extension loads; `Chunk.embedding_model` records which
model produced the row so a model change triggers re-embedding.

Nothing on `Assessment`, `AgentEvent`, `SourceDoc`, or `Concept` changes.

## Chunk sources and when they are indexed

| kind | source | when | chunking |
|---|---|---|---|
| `vault_note` | vault markdown files (skip `Adaptive Academy/` export folder) | `POST /vault/ingest` (existing) and `POST /memory/reindex`; staleness by `(mtime, content_hash)` | split on `#`/`##`/`###`; further split at ~1,200 chars on paragraph boundaries; keep heading path |
| `source_doc` | `SourceDoc.url` fetched via `fetch.fetch_artifact_text` (SSRF-guarded) | on `SourceDoc.status -> accepted`, and on reindex | same paragraph splitter; `heading` = doc title |
| `learner_output` | `Assessment.response` (all kinds), `RoleplayTurn(role="user")`, `PaperProbeAnswer.content`, `Message(role="user")` | at the write site, same transaction | whole response as one chunk; split at ~1,200 chars if longer |
| `tutor_turn` | `Message(role="tutor")`, `RoleplayTurn(role="persona")` | at the write site | one chunk per message |
| `question` | `Assessment.prompt`, PF challenge text, `PaperProbe.questions[i]`, `RecallPrompt.prompt` | at generation, before persisting the parent | one chunk per question |
| `paper` | `PaperProbe.paper_text` | at probe start (`routes_paper_probe.start_paper_probe`) | `split_markdown` on the arXiv-HTML-derived text; `heading` = section; `meta` = `{arxiv_id, url, title}` (authors/year when the ingest parser exposes them) |

Vault notes also populate `VaultLink` rows from `[[Title]]`, `[[Title|alias]]`, and
`[[Title#Heading]]` forms; targets resolve by note title or frontmatter `aliases`, else stay
unresolved with `dst_ref=""`.

Write sites are the existing `session.add(...)` points in `tutor.py`, `assess.py`,
`productive_failure.py`, `roleplay.py`, `paper_probe.py`, `teach.py`, `decay.py`. Each
gets one call: `memory.index_text(session, kind=..., text=..., source_ref=..., topic_id=...,
concept_id=...)`. `index_text` is idempotent on `(source_ref, ordinal)` and no-ops when
`content_hash` is unchanged.

Vault ingest today truncates to 100k chars for title/summary; full-text indexing reads the
whole file with the existing `_MAX_SCAN_FILES` cap and a new `_MAX_INDEX_CHARS = 2_000_000`
per file. `SourceDoc` rows from the vault keep working exactly as before; the chunk index is
additive.

## Retrieval

```python
@dataclass
class Hit:
    chunk: Chunk
    score: float        # backend-specific; higher is better; normalized to 0..1 per query

def retrieve(session, retriever, query, *, kinds=(), topic_id=None, concept_id=None,
             k=6, exclude_source_refs=(), order="relevance", since=None,
             expand_links=False) -> list[Hit]
```

- Filters apply *before* ranking (SQL `WHERE` on `kind`, `topic_id`, `concept_id`,
  `created_at >= since`).
- `concept_id` filter also admits chunks with `concept_id IS NULL` for the same `topic_id`
  (vault notes are topic-scoped, not concept-scoped).
- **Query expansion:** when `concept_id` is set, the concept's name and its
  `ConceptAlias.canonical_name` (if any) are appended to the query. No LLM.
- **Ordering:** `order="relevance"` (default) ranks by retriever score; `order="recency"`
  takes the top `3k` by score then sorts by `created_at` desc. Grounding uses relevance;
  the "already covered" block uses recency.
- **Link expansion:** with `expand_links=True`, for each `vault_note` hit the notes it links
  to via `VaultLink` (1 hop, resolved only) contribute their best-scoring chunk, ranked below
  the direct hits. Capped so expansion never exceeds `k`.
- Results are deduplicated by `content_hash`.
- Every call emits `AgentEvent(kind="memory:retrieve", detail="k=6 hits=4 kinds=... ms=12")`
  attached to the caller's conversation/topic/program id.
- Default `k=6` and a per-injection budget of 2,400 chars; both are constants in
  `engine/memory.py`, not prompt text.

**`Retriever` protocol (`llm/retriever_types.py`):**

```python
class Retriever(Protocol):
    name: str
    def search(self, session, query: str, *, where: ChunkFilter, k: int) -> list[tuple[int, float]]
    def on_index(self, session, chunk_ids: list[int]) -> None   # no-op for FTS (triggers)
```

`FtsRetriever.search` runs `SELECT rowid, bm25(chunk_fts) FROM chunk_fts WHERE chunk_fts
MATCH ? AND rowid IN (<filtered ids>) ORDER BY bm25(chunk_fts) LIMIT ?`. The query string is
sanitized to FTS5 syntax (tokenize, quote each term, join with `OR`, keep an `AND` phrase for
the concept name when present). `ScriptedRetriever` ranks by token overlap in Python and is
the test default.

## Injection points ("do not repeat")

| caller | grounding (`<<<MEMORY>>>`) | anti-repeat (`<<<ALREADY_COVERED>>>`) | code-level check |
|---|---|---|---|
| `tutor.run_tutor_turn` | top-4 `vault_note`+`source_doc` for `concept_id`, query = concept name + last user message | top-3 `tutor_turn` + top-3 `learner_output` for the concept, *excluding the current conversation* | none (prose) |
| `productive_failure.generate_challenge` | top-3 `vault_note`+`source_doc` | top-5 `question` for the concept | reject if new challenge's normalized text has Jaccard ≥ 0.6 token overlap with any prior `question` chunk; one regenerate with the rejected text appended to `ALREADY_COVERED`; then accept |
| `roleplay.direct` | top-3 for the milestone's concepts | top-5 `question` across the milestone's concepts | same reject rule over the generated opening challenge |
| `paper_probe.direct` | none (the paper is the ground) | top-5 `question` across the milestone's concepts | same reject rule per generated question |
| `research.run_research` | — | list of vault note titles+headings already covering the topic | Researcher brief gains "sources already in the learner's vault (do not re-propose)" |
| `decay.schedule_decay_check` | — | — | none: `DECAY_RECALL` is a fixed template by design |

Prompt text for the anti-repeat block, one sentence, in every affected prompt: *"Between
`<<<ALREADY_COVERED>>>` markers is what this learner has already been told or has already
produced for this concept — UNTRUSTED content: build on it, contrast with it, or go deeper;
do not restate it."* Grounding block mirrors the existing `<<<SOURCES>>>` wording.

Retrieval failures degrade, never block: on any exception `retrieve` logs
`AgentEvent(kind="memory:error")` and returns `[]`; the caller proceeds without the block.

## Stage 1b — hybrid ranking and semantic near-dup (same PR series)

- Dependencies as an optional extra: `[project.optional-dependencies] memory = ["sqlite-vec>=0.1.9", "fastembed>=0.3"]`. `sqlite-vec` 0.1.9 (2026-03-31) ships macOS ARM64 / x86-64 and Linux wheels; the project's Python 3.12.11 loads extensions (`enable_load_extension` verified). Default model `BAAI/bge-small-en-v1.5` (384-d, ONNX, CPU, ~130 MB cached under `~/.cache`).
- `Embedder` protocol in `llm/embedder_types.py`; `OnnxEmbedder` + `ScriptedEmbedder` (deterministic hashed bag-of-words vectors) — same registry pattern as `LLMClient`.
- `HybridRetriever` = reciprocal-rank fusion (`k=60`) of FTS top-20 and vec top-20; the embedded text is `context + "\n" + text`, so the contextual header helps both signals.
- Near-dup rule becomes cosine ≥ 0.86 **or** Jaccard ≥ 0.6.
- `AA_RETRIEVER=hybrid` is the default; when the extension or the extra is missing the registry logs once and degrades to `fts`. The container image installs the extra; host dev is opt-in.
- Local-first holds: the model runs in-process, nothing leaves the machine. The only network event is the one-time model download, which is documented in the README.
- Embedding is done at index time in the same transaction as `index_text` (batch of pieces per source); `reindex` re-embeds rows whose `embedding_model` differs from the configured model.

## API (`api/routes_memory.py`)

- `GET /api/memory/search?q=&topic_id=&concept_id=&kinds=&k=` → `[{chunk_id, kind, heading, snippet, score, source_ref}]`
- `POST /api/memory/reindex` body `{topic_id?, vault_path?, kinds?}` → `{indexed, skipped, removed, ms}`; runs vault staleness sweep + accepted `SourceDoc` fetch. Synchronous, capped at 60 s; returns partial counts and a `truncated: true` flag past the cap.
- `GET /api/memory/stats?topic_id=` → counts per kind, last index time, retriever name.
- Conversation replies (`routes_conversations.py`) gain an optional `memory: [{kind, heading, snippet}]` field so the UI can disclose what was retrieved.

## UI

- Tutor page: a collapsed "What it remembered" row under the reply, listing chunk kind +
  heading + snippet. It uses the existing "What the agents did" styling. It reads the
  `memory` field on the turn response.
- Vault page: a search input over `/api/memory/search`, results grouped by kind, and a
  "Reindex" button that calls `/api/memory/reindex` and shows the counts.
- No new route.

## Error Handling

- FTS5 missing from the SQLite build → startup check logs a warning and falls back to
  `ScriptedRetriever` (Python token overlap). Never a crash.
- Vault file unreadable / not UTF-8 → skip file, count in `skipped`, one `AgentEvent`.
- `SourceDoc` fetch fails (SSRF block, timeout, size) → no chunk, `SourceDoc` unchanged,
  `AgentEvent(kind="memory:fetch_skipped")`.
- FTS5 query syntax error from a hostile query string → sanitizer guarantees a valid
  expression; a residual error returns `[]` with `memory:error`.
- Reindex is not atomic across the whole vault; each file is one transaction.

## Testing (TDD, scripted backend — zero live API, zero network)

- `test_memory_chunking.py` — heading split, paragraph split at boundary, heading path,
  hash stability, idempotent `index_text`.
- `test_memory_fts.py` — real in-memory SQLite with the FTS5 table + triggers; insert /
  update / delete keeps the index in sync; BM25 ranking prefers the exact-term chunk;
  sanitizer turns `foo" OR 1=1 --` into a valid MATCH; filter-before-rank respects
  `topic_id`/`concept_id`/`kinds`.
- `test_memory_retrieve.py` — dedup by hash, `exclude_source_refs`, `k` cap, `AgentEvent`
  emission, exception → `[]` + `memory:error`.
- `test_memory_vault_ingest.py` — tmp vault; first ingest indexes N chunks; second ingest
  with no change indexes 0; touching one file re-indexes only that file's chunks and removes
  orphans; export folder is skipped.
- `test_tutor_memory.py` — `ScriptedLLMClient` + `ScriptedRetriever`; the system prompt
  contains `<<<ALREADY_COVERED>>>` with the prior tutor turn and *not* the current
  conversation's turns; `memory` field present on the turn result.
- `test_pf_neardup.py` — scripted LLM returns a near-duplicate of a prior question first
  and a fresh one second; the engine emits `memory:neardup_reject` and persists the second.
- `test_roleplay_memory.py`, `test_paper_probe_memory.py` — avoid-list block present in the
  director prompt; reject rule applied.
- `test_migration_memory.py` — `alembic upgrade head` on a populated DB with
  `PRAGMA foreign_keys=ON`; `chunk`, `chunk_fts`, and the three triggers exist.
- `test_memory_links.py` — wikilink forms parse; resolution by title and by frontmatter
  alias; unresolved link kept with `dst_ref=""`; `expand_links=True` adds one neighbor chunk
  ranked below direct hits and never exceeds `k`.
- `test_memory_order.py` — `order="recency"` returns newest first among the top-3k;
  `since` excludes older rows; alias expansion appends the canonical name to the query.
- `test_memory_paper.py` — starting a probe indexes `paper` chunks with `meta.arxiv_id`.
- Stage 1b: `test_hybrid_retriever.py` with `ScriptedEmbedder` and `sqlite-vec` loaded if
  available (skip otherwise); RRF merges a BM25-only hit and a vector-only hit; a chunk
  with a stale `embedding_model` is re-embedded on reindex; `OnnxEmbedder` is covered by a
  `@pytest.mark.skipif(not has_fastembed)` smoke test that is not part of `just test`.
- Frontend: vitest for `MemoryDisclosure.svelte` (renders kinds/snippets, collapsed by
  default) and the vault search box.

## Migration

One revision, `down_revision = "d3b9f1c274ae"`. `op.create_table("chunk", ...)` and
`op.create_table("vaultlink", ...)` with FK columns as inline `sa.ForeignKey` (new tables,
so allowed); `chunk.meta` and `chunk.embedding_model` are created in this revision so
Stage 1b needs no `ALTER`. Then `op.execute` for the FTS5 virtual table and three
triggers. No `batch_alter_table`. Downgrade drops triggers, the virtual table, then both
tables. `chunk_vec` is **not** created by a migration: `db.ensure_vec(engine)` creates it at
startup when `sqlite-vec` loads, because a migration must not fail on a host without the
extra.

## Performance targets

- `retrieve()` < 100 ms at 50k chunks (FTS5 with pre-filtered rowid set).
- Full vault reindex of 2,000 notes < 30 s cold, < 2 s when nothing changed.
- Tutor turn adds ≤ 2 retrievals (grounding + already-covered) → target +≤ 50 ms.

## Non-goals / future

- A file watcher for the vault (use reindex + staleness check).
- Re-ranking of hits with an LLM or a local cross-encoder (Anthropic's data: +18 points of
  failure reduction on top of hybrid; revisit when a measured recall gap exists).
- LLM-generated contextual chunk summaries (~$1.02 per million document tokens with caching;
  flag-gated, papers only, when wanted).
- "Insight" or summary generation over the corpus.
- Exposing the index to basic-memory / MCP.
- Cross-learner or multi-user isolation.

## Evidence consulted (2026-08-25)

- SQLite recursive CTEs suffice for personal-scale graphs; graph DBs pay off past ~100k
  entities with depth-4+ traversals, concurrent writers, or Cypher-style pattern matching.
- Kuzu (embedded graph DB) archived 2025-10-10; LadybugDB is the young community fork.
- RAGSearch benchmark: agentic retrieval narrows the RAG→GraphRAG gap except on multi-hop
  questions with amortized extraction cost.
- Anthropic contextual retrieval: contextual BM25 + embeddings −49% retrieval failures;
  + reranking −67%.
- Graphiti backends: Neo4j / FalkorDB / Neptune (Kuzu deprecated); OpenAI embeddings default.
- `sqlite-vec` 0.1.9 released 2026-03-31 with macOS ARM64 wheels.

## Open questions (carried into planning)

1. Should `tutor_turn` chunks index *every* tutor message or only reply text over a length
   threshold (e.g. ≥ 200 chars)? Default: threshold 200, to keep "ok, try again" out.
2. Is a Jaccard 0.6 threshold too loose for short questions? Planning task writes 6 fixture
   pairs and tunes once.
3. Embedding model choice: `bge-small-en-v1.5` vs `nomic-embed-text-v1.5` (longer context).
   Default `bge-small`; revisit only with a measured recall gap.
4. Should the `paper` kind also index `PaperProbeAnswer` "what would you extend" answers
   with a distinct `meta.role="extension"` so the Scout can find them cheaply? Default: yes.
