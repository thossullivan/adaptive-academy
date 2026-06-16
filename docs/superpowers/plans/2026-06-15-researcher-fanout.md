# Researcher (fan-out) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hand-seeded Topic with a real one — a structured onboarding intake creates a Topic; a fan-out Researcher (parallel web-search subagents) gathers, dedups, ranks, and synthesizes foundational sources into a `TopicFoundation` + tiered `SourceDoc` reading list that the user reviews and prunes before it is saved.

**Architecture:** Extends the Plan 1 walking skeleton. Pure deterministic helpers (`build_briefs`, `canonicalize_url`, `dedupe_by_url`, `rank_sources`) + an LLM synthesis step are composed by a `research_topic()` orchestrator that fans out over a `ResearcherClient` Protocol (real impl = Anthropic Messages web-search tool; test double = scripted). FastAPI routes drive onboarding → research → review; SvelteKit adds `/topics/new` and `/topics/[id]/review`. All automated tests use scripted clients; dedup/ranking are pure and independently tested.

**Tech Stack:** Python 3.12 · FastAPI · SQLModel + SQLite (WAL) · Alembic (batch mode) · Anthropic SDK · SvelteKit 2 / Svelte 5 (runes) / Tailwind 4 · pytest · vitest.

**Spec:** `docs/superpowers/specs/2026-06-15-researcher-fanout.md` (read §2 decisions, §4 data model, §5 API, §7 tests).

**Conventions to follow (from Plan 1 — do NOT reinvent):**
- LLM seam: `LLMClient` Protocol in `src/adaptive_academy/llm/types.py` (`complete(system, messages, tools) -> LLMResponse`); scripted double `ScriptedLLMClient(responses)`.
- DB: `src/adaptive_academy/db.py` (`engine`, `create_db_and_tables`), pragmas WAL + foreign_keys.
- API factory: `src/adaptive_academy/api/app.py` (`create_app()`); deps in `api/deps.py` (`get_session`, `get_llm`); existing routes in `api/routes_topics.py`, `api/routes_conversations.py`; schemas in `api/schemas.py`.
- Observability: `AgentEvent` table.
- Tests live in `tests/`; `tests/conftest.py` provides an in-memory SQLite `session` fixture (StaticPool). Run with `uv run pytest -q`.
- Frontend: `frontend/src/lib/{api.ts,types.ts}`, routes under `frontend/src/routes/`, vitest, vite proxy `/api`→:8000.

---

## File Structure (created or modified)

- Create: `src/adaptive_academy/llm/researcher_types.py` — `SearchBrief`, `RawSource`, `ResearcherClient` Protocol.
- Create: `src/adaptive_academy/llm/scripted_researcher.py` — `ScriptedResearcherClient` test double.
- Create: `src/adaptive_academy/llm/anthropic_researcher.py` — real web-search client.
- Create: `src/adaptive_academy/engine/research.py` — pure helpers + `synthesize_foundation` + `research_topic` orchestrator.
- Modify: `src/adaptive_academy/models.py` — add `TopicIntent`, `SourceDoc`, `TopicFoundation`; generalize `AgentEvent`.
- Create: `alembic/versions/<rev>_researcher.py` — migration.
- Modify: `src/adaptive_academy/api/schemas.py` — new Pydantic schemas; extend `TopicOut`.
- Modify: `src/adaptive_academy/api/deps.py` — `get_researcher()`.
- Modify: `src/adaptive_academy/api/routes_topics.py` — create-topic, research, sources, review, foundation.
- Create: `frontend/src/routes/topics/new/+page.svelte`, `frontend/src/routes/topics/[id]/review/+page.svelte`.
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/routes/+page.svelte` (nav link).
- Create/modify tests under `tests/` and `frontend/src/lib/api.test.ts`.

---

## Task 1: Data model — new tables + AgentEvent generalization

**Files:**
- Modify: `src/adaptive_academy/models.py`
- Test: `tests/test_research_models.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_models.py`:

```python
from sqlmodel import Session, select

from adaptive_academy.models import (
    AgentEvent,
    SourceDoc,
    Topic,
    TopicFoundation,
    TopicIntent,
)


def test_topic_intent_roundtrip(session: Session):
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    session.add(
        TopicIntent(
            topic_id=topic.id,
            goal="Understand transformers end to end",
            prior_knowledge="Strong math, some PyTorch",
            time_budget="~10 hrs/week",
        )
    )
    session.commit()
    intent = session.exec(select(TopicIntent)).one()
    assert intent.goal.startswith("Understand")
    assert intent.time_budget == "~10 hrs/week"


def test_sourcedoc_defaults_and_json_foundation(session: Session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(
        SourceDoc(topic_id=topic.id, title="Attention Is All You Need", url="https://arxiv.org/abs/1706.03762", tier=1)
    )
    session.add(
        TopicFoundation(
            topic_id=topic.id,
            overview="Transformers replace recurrence with attention.",
            key_concepts=["self-attention", "positional encoding"],
            prerequisite_map={"self-attention": ["dot product", "softmax"]},
        )
    )
    session.commit()
    sd = session.exec(select(SourceDoc)).one()
    assert sd.status == "proposed"
    assert sd.added_by == "researcher"
    assert sd.rank == 0
    fnd = session.exec(select(TopicFoundation)).one()
    assert fnd.key_concepts == ["self-attention", "positional encoding"]
    assert fnd.prerequisite_map["self-attention"] == ["dot product", "softmax"]


def test_agentevent_attaches_to_topic(session: Session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(AgentEvent(topic_id=topic.id, kind="research:done", detail="3 sources"))
    session.commit()
    ev = session.exec(select(AgentEvent)).one()
    assert ev.topic_id == topic.id
    assert ev.conversation_id is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_research_models.py -q`
Expected: FAIL — `ImportError` (SourceDoc/TopicFoundation/TopicIntent not defined) / `AgentEvent` has no `topic_id`.

- [ ] **Step 3: Edit `src/adaptive_academy/models.py`**

Add the JSON import at the top (after existing imports):

```python
from typing import Any, Optional

from sqlalchemy import Column, JSON
from sqlmodel import Field, Relationship, SQLModel
```

(Keep the existing `from datetime import ...` and `_now()` helper.)

Append the three new tables at the end of the file:

```python
class TopicIntent(SQLModel, table=True):
    """Structured onboarding brainstorm captured when a Topic is created."""

    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", unique=True)
    goal: str
    prior_knowledge: str = ""
    time_budget: str = ""
    created_at: datetime = Field(default_factory=_now)


class SourceDoc(SQLModel, table=True):
    """A foundational source surfaced by the Researcher (tiered reading list)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id")
    title: str
    url: str
    tier: int = 3  # 1 (authoritative) | 2 (synthesis) | 3 (supporting)
    summary: str = ""
    why: str = ""
    relevance: float = 0.0  # subagent-reported, 0..1
    rank: int = 0  # 0-based position after rank_sources
    angle: str = ""  # which brief surfaced it
    status: str = "proposed"  # proposed | accepted | pruned
    added_by: str = "researcher"
    created_at: datetime = Field(default_factory=_now)


class TopicFoundation(SQLModel, table=True):
    """Synthesized overview + concept map for a Topic (decoupled from Track/Concept)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", unique=True)
    overview: str = ""
    key_concepts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    prerequisite_map: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
```

Generalize `AgentEvent` — change `conversation_id` to nullable and add `topic_id`:

```python
class AgentEvent(SQLModel, table=True):
    """Observability trace: one row per engine/agent step.

    Exactly one of conversation_id / topic_id is set (app-level invariant).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id")
    topic_id: Optional[int] = Field(default=None, foreign_key="topic.id")
    kind: str
    detail: str = ""
    created_at: datetime = Field(default_factory=_now)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_models.py tests/test_models.py -q`
Expected: PASS (new tests pass; Plan 1 `test_models.py` still passes — `AgentEvent` change is backward-compatible since `conversation_id` was already always provided).

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/models.py tests/test_research_models.py
git commit -m "feat(models): TopicIntent, SourceDoc, TopicFoundation + topic-scoped AgentEvent"
```

---

## Task 2: Alembic migration (batch mode)

**Files:**
- Create: `alembic/versions/<rev>_researcher.py`

- [ ] **Step 1: Autogenerate the migration**

Run: `uv run alembic revision --autogenerate -m "researcher tables"`
Expected: a new file under `alembic/versions/`. It should add `topicintent`, `sourcedoc`, `topicfoundation` tables and alter `agentevent` (add `topic_id`, make `conversation_id` nullable).

- [ ] **Step 2: Fix the generated migration**

Open the new file. Apply these known fixes (same quirks as the Plan 1 baseline):
1. Ensure `import sqlmodel` is present at the top (SQLModel `AutoString` columns reference it).
2. Ensure the `agentevent` alteration uses **batch mode**. If autogenerate emitted `op.add_column` / `op.alter_column` directly, wrap them:

```python
with op.batch_alter_table("agentevent") as batch_op:
    batch_op.add_column(sa.Column("topic_id", sa.Integer(), nullable=True))
    batch_op.alter_column("conversation_id", existing_type=sa.Integer(), nullable=True)
    batch_op.create_foreign_key("fk_agentevent_topic_id", "topic", ["topic_id"], ["id"])
```

3. JSON columns on `sourcedoc`/`topicfoundation` should be `sa.JSON()`. If autogenerate produced `sqlite.JSON`, change to `sa.JSON()` for portability.
4. Verify `downgrade()` reverses each operation (drop tables; batch-drop `topic_id`; restore `conversation_id` NOT NULL).

- [ ] **Step 3: Apply and verify the migration round-trips**

```bash
rm -f adaptive_academy.db
uv run alembic upgrade head
uv run alembic downgrade -1
uv run alembic upgrade head
```

Expected: all three commands exit 0. Then sanity-check the schema:

Run: `uv run python -c "import sqlite3; c=sqlite3.connect('adaptive_academy.db'); print(sorted(r[0] for r in c.execute('select name from sqlite_master where type=\"table\"')))"`
Expected: includes `agentevent, sourcedoc, topicfoundation, topicintent, topic, track, concept, knowledgeestimate, conversation, message`.

- [ ] **Step 4: Commit**

```bash
git add alembic/versions/
git commit -m "feat(db): migration for researcher tables + topic-scoped AgentEvent"
```

---

## Task 3: ResearcherClient types + scripted double

**Files:**
- Create: `src/adaptive_academy/llm/researcher_types.py`
- Create: `src/adaptive_academy/llm/scripted_researcher.py`
- Test: `tests/test_scripted_researcher.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_scripted_researcher.py`:

```python
import pytest

from adaptive_academy.llm.researcher_types import RawSource, SearchBrief
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient


def test_scripted_returns_canned_sources_by_angle():
    client = ScriptedResearcherClient(
        {
            "foundational_papers": [
                RawSource(title="Attention", url="https://arxiv.org/abs/1706.03762", tier=1, relevance=0.95)
            ],
            "critiques": [],
        }
    )
    brief = SearchBrief(angle="foundational_papers", query="transformer foundational papers")
    out = client.search(brief)
    assert len(out) == 1
    assert out[0].title == "Attention"
    assert client.calls == ["foundational_papers"]


def test_scripted_unknown_angle_returns_empty():
    client = ScriptedResearcherClient({})
    assert client.search(SearchBrief(angle="whatever", query="q")) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_scripted_researcher.py -q`
Expected: FAIL — `ModuleNotFoundError: adaptive_academy.llm.researcher_types`.

- [ ] **Step 3: Create `src/adaptive_academy/llm/researcher_types.py`**

```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class SearchBrief:
    """One fan-out angle: a sub-question the Researcher searches the web for."""

    angle: str  # stable key, e.g. "foundational_papers"
    query: str  # the web-search query / instruction


@dataclass
class RawSource:
    """A candidate source returned by a subagent (pre-dedup, pre-rank)."""

    title: str
    url: str
    tier: int = 3  # 1 | 2 | 3
    summary: str = ""
    why: str = ""
    relevance: float = 0.0  # 0..1
    angle: str = ""  # stamped by the orchestrator from the brief


class ResearcherClient(Protocol):
    """A single fan-out subagent: searches the web for one brief, returns sources."""

    def search(self, brief: SearchBrief) -> list[RawSource]: ...
```

- [ ] **Step 4: Create `src/adaptive_academy/llm/scripted_researcher.py`**

```python
import threading

from adaptive_academy.llm.researcher_types import RawSource, SearchBrief


class ScriptedResearcherClient:
    """Test double: returns canned RawSources keyed by brief angle. Thread-safe."""

    def __init__(self, by_angle: dict[str, list[RawSource]]):
        self._by_angle = by_angle
        self._lock = threading.Lock()
        self.calls: list[str] = []

    def search(self, brief: SearchBrief) -> list[RawSource]:
        with self._lock:
            self.calls.append(brief.angle)
        return list(self._by_angle.get(brief.angle, []))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_scripted_researcher.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/adaptive_academy/llm/researcher_types.py src/adaptive_academy/llm/scripted_researcher.py tests/test_scripted_researcher.py
git commit -m "feat(llm): ResearcherClient protocol + scripted fan-out double"
```

---

## Task 4: `build_briefs` (deterministic fan-out angles)

**Files:**
- Create: `src/adaptive_academy/engine/research.py`
- Test: `tests/test_research_briefs.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_briefs.py`:

```python
from adaptive_academy.engine.research import ANGLES, build_briefs
from adaptive_academy.llm.researcher_types import SearchBrief


def test_build_briefs_count_and_determinism():
    a = build_briefs("Build LLMs from scratch", "learn transformers", 5)
    b = build_briefs("Build LLMs from scratch", "learn transformers", 5)
    assert len(a) == 5
    assert a == b  # deterministic
    assert all(isinstance(x, SearchBrief) for x in a)


def test_build_briefs_caps_to_available_angles():
    out = build_briefs("Topic", "intent", 99)
    assert len(out) == len(ANGLES)


def test_build_briefs_embeds_topic_in_query():
    out = build_briefs("Diffusion models", "intent", 3)
    assert all("Diffusion models" in b.query for b in out)
    assert [b.angle for b in out] == [a[0] for a in ANGLES[:3]]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_research_briefs.py -q`
Expected: FAIL — `ModuleNotFoundError: adaptive_academy.engine.research`.

- [ ] **Step 3: Create `src/adaptive_academy/engine/research.py` with `ANGLES` + `build_briefs`**

```python
from adaptive_academy.llm.researcher_types import SearchBrief

# (angle_key, query_template) — {topic} is filled in. Order is the fan-out order.
ANGLES: list[tuple[str, str]] = [
    ("foundational_papers", "Seminal / foundational papers for learning {topic}"),
    ("canonical_tutorials", "Best canonical tutorials, courses, or lectures for {topic}"),
    ("key_concepts", "Key concepts and prerequisites someone must understand for {topic}"),
    ("reference_implementations", "Well-regarded reference implementations or codebases for {topic}"),
    ("critiques", "Critiques, limitations, and common misconceptions about {topic}"),
]


def build_briefs(topic: str, intent: str, n: int) -> list[SearchBrief]:
    """Deterministic fan-out angles. Caps at the number of defined ANGLES."""
    count = max(0, min(n, len(ANGLES)))
    briefs: list[SearchBrief] = []
    for angle, template in ANGLES[:count]:
        query = template.format(topic=topic)
        if intent:
            query = f"{query}. Learner goal: {intent}"
        briefs.append(SearchBrief(angle=angle, query=query))
    return briefs
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_briefs.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/research.py tests/test_research_briefs.py
git commit -m "feat(research): deterministic build_briefs fan-out angles"
```

---

## Task 5: `canonicalize_url` + `dedupe_by_url` (pure)

**Files:**
- Modify: `src/adaptive_academy/engine/research.py`
- Test: `tests/test_research_dedup.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_dedup.py`:

```python
from adaptive_academy.engine.research import canonicalize_url, dedupe_by_url
from adaptive_academy.llm.researcher_types import RawSource


def test_canonicalize_strips_scheme_www_slash_and_tracking():
    a = canonicalize_url("https://www.Example.com/path/?utm_source=x&id=7#frag")
    b = canonicalize_url("http://example.com/path?id=7")
    assert a == b == "example.com/path?id=7"


def test_canonicalize_keeps_meaningful_query_sorted():
    assert canonicalize_url("https://youtube.com/watch?v=abc&t=10") == "youtube.com/watch?t=10&v=abc"


def test_dedupe_merges_duplicates_keeping_richer_record():
    src = [
        RawSource(title="Attention", url="https://arxiv.org/abs/1706.03762", tier=1, relevance=0.9, summary=""),
        RawSource(title="Attention (dup)", url="http://www.arxiv.org/abs/1706.03762/", tier=1, relevance=0.8, summary="A summary"),
        RawSource(title="Other", url="https://example.com/x", tier=2, relevance=0.5),
    ]
    out = dedupe_by_url(src)
    assert len(out) == 2
    kept = next(s for s in out if "arxiv" in s.url)
    assert kept.summary == "A summary"  # richer record won


def test_dedupe_is_deterministic_in_order():
    src = [
        RawSource(title="B", url="https://b.com", tier=2, relevance=0.5),
        RawSource(title="A", url="https://a.com", tier=1, relevance=0.9),
    ]
    assert [s.url for s in dedupe_by_url(src)] == ["https://a.com", "https://b.com"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_research_dedup.py -q`
Expected: FAIL — `ImportError` (`canonicalize_url`, `dedupe_by_url` not defined).

- [ ] **Step 3: Add to `src/adaptive_academy/engine/research.py`**

Add imports at the top of the file:

```python
from urllib.parse import parse_qsl, urlencode, urlsplit

from adaptive_academy.llm.researcher_types import RawSource, SearchBrief
```

(Replace the existing single import line with this combined import.)

Add the functions:

```python
_TRACKING = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ref", "ref_src", "mc_cid", "mc_eid",
}


def canonicalize_url(url: str) -> str:
    """Normalize a URL for dedup: drop scheme/www/trailing-slash/fragment/tracking params."""
    raw = url.strip()
    parts = urlsplit(raw if "//" in raw else "//" + raw)
    host = (parts.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    path = parts.path.rstrip("/")
    kept = [(k, v) for k, v in parse_qsl(parts.query) if k.lower() not in _TRACKING]
    query = urlencode(sorted(kept))
    canon = host + path
    if query:
        canon += "?" + query
    return canon


def _richness(s: RawSource) -> tuple:
    """Higher is richer: prefer a summary, then a why, then relevance, then tier."""
    return (bool(s.summary), bool(s.why), s.relevance, -s.tier)


def dedupe_by_url(sources: list[RawSource]) -> list[RawSource]:
    """Collapse duplicate URLs, keeping the richest record. Deterministic order (by canonical url)."""
    best: dict[str, RawSource] = {}
    for s in sources:
        key = canonicalize_url(s.url)
        if key not in best or _richness(s) > _richness(best[key]):
            best[key] = s
    return [best[k] for k in sorted(best)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_dedup.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/research.py tests/test_research_dedup.py
git commit -m "feat(research): pure canonicalize_url + dedupe_by_url"
```

---

## Task 6: `rank_sources` (pure, deterministic total order)

**Files:**
- Modify: `src/adaptive_academy/engine/research.py`
- Test: `tests/test_research_rank.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_rank.py`:

```python
from adaptive_academy.engine.research import rank_sources, score_source
from adaptive_academy.llm.researcher_types import RawSource


def test_score_weights_tier_and_relevance():
    hi = RawSource(title="A", url="a", tier=1, relevance=0.9)
    lo = RawSource(title="B", url="b", tier=3, relevance=0.4)
    assert score_source(hi) > score_source(lo)


def test_rank_orders_by_score_desc_with_stable_url_tiebreak():
    src = [
        RawSource(title="t3", url="https://c.com", tier=2, relevance=0.5),
        RawSource(title="t1", url="https://a.com", tier=1, relevance=0.9),
        RawSource(title="t2", url="https://b.com", tier=1, relevance=0.9),  # ties with a.com on score
    ]
    out = rank_sources(src)
    assert [s.url for s in out] == ["https://a.com", "https://b.com", "https://c.com"]
    # tie between a.com and b.com broken by url ascending


def test_rank_is_pure_does_not_mutate_input():
    src = [RawSource(title="x", url="x", tier=3, relevance=0.1)]
    before = list(src)
    rank_sources(src)
    assert src == before
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_research_rank.py -q`
Expected: FAIL — `ImportError` (`rank_sources`, `score_source`).

- [ ] **Step 3: Add to `src/adaptive_academy/engine/research.py`**

```python
_TIER_SCORE = {1: 1.0, 2: 0.6, 3: 0.3}
_W_TIER = 0.6
_W_REL = 0.4


def score_source(s: RawSource) -> float:
    """Deterministic relevance/authority score in [0, 1]."""
    tier = _TIER_SCORE.get(s.tier, 0.3)
    rel = max(0.0, min(1.0, s.relevance))
    return _W_TIER * tier + _W_REL * rel


def rank_sources(sources: list[RawSource]) -> list[RawSource]:
    """Return a new list ordered by score desc, tie-broken by url ascending (total order)."""
    return sorted(sources, key=lambda s: (-score_source(s), s.url))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_rank.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/research.py tests/test_research_rank.py
git commit -m "feat(research): deterministic rank_sources"
```

---

## Task 7: `synthesize_foundation` (LLM structured synthesis)

**Files:**
- Modify: `src/adaptive_academy/engine/research.py`
- Test: `tests/test_research_synthesis.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_synthesis.py`:

```python
import json

from adaptive_academy.engine.research import Foundation, synthesize_foundation
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse


def _payload() -> str:
    return json.dumps(
        {
            "overview": "Transformers use attention.",
            "key_concepts": ["self-attention", "softmax"],
            "prerequisite_map": {"self-attention": ["dot product"]},
        }
    )


def test_synthesize_parses_plain_json():
    llm = ScriptedLLMClient([LLMResponse(text=_payload())])
    f = synthesize_foundation("LLMs", "learn", [RawSource(title="A", url="a", tier=1)], llm)
    assert isinstance(f, Foundation)
    assert f.overview == "Transformers use attention."
    assert f.key_concepts == ["self-attention", "softmax"]
    assert f.prerequisite_map == {"self-attention": ["dot product"]}


def test_synthesize_strips_markdown_fences():
    llm = ScriptedLLMClient([LLMResponse(text="```json\n" + _payload() + "\n```")])
    f = synthesize_foundation("LLMs", "learn", [], llm)
    assert f.key_concepts == ["self-attention", "softmax"]


def test_synthesize_includes_sources_in_prompt():
    llm = ScriptedLLMClient([LLMResponse(text=_payload())])
    synthesize_foundation("LLMs", "learn", [RawSource(title="Attention Paper", url="u", tier=1)], llm)
    sent = llm.calls[0]["messages"][0]["content"]
    assert "Attention Paper" in sent
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_research_synthesis.py -q`
Expected: FAIL — `ImportError` (`Foundation`, `synthesize_foundation`).

- [ ] **Step 3: Add to `src/adaptive_academy/engine/research.py`**

Add imports/standard lib at the top (extend the existing import block):

```python
import json
from dataclasses import dataclass

from adaptive_academy.llm.types import LLMClient
```

Add the dataclass, prompt builder, parser, and function:

```python
_FOUNDATION_SYSTEM = (
    "You are a research synthesizer for a self-directed advanced adult learner. "
    "Given a topic, the learner's intent, and a ranked reading list, produce a concise "
    "foundation. Respond with ONLY a JSON object with keys: "
    '"overview" (string, 2-4 sentences), "key_concepts" (array of short strings, the '
    'load-bearing ideas), "prerequisite_map" (object mapping each key concept to an array '
    "of prerequisite concept names). No prose outside the JSON."
)


@dataclass
class Foundation:
    overview: str
    key_concepts: list[str]
    prerequisite_map: dict


def _build_foundation_user_msg(topic: str, intent: str, sources: list[RawSource]) -> str:
    lines = [f"TOPIC: {topic}", f"LEARNER INTENT: {intent}", "", "READING LIST:"]
    for s in sources:
        lines.append(f"- [{s.tier}] {s.title} ({s.url}) — {s.summary}".rstrip(" —"))
    return "\n".join(lines)


def _parse_foundation_json(text: str) -> Foundation:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
        cleaned = cleaned.strip()
    data = json.loads(cleaned)
    return Foundation(
        overview=str(data.get("overview", "")),
        key_concepts=list(data.get("key_concepts", [])),
        prerequisite_map=dict(data.get("prerequisite_map", {})),
    )


def synthesize_foundation(
    topic: str, intent: str, sources: list[RawSource], llm: LLMClient
) -> Foundation:
    """Single structured LLM call → Foundation (overview + concepts + prereq map)."""
    user_msg = _build_foundation_user_msg(topic, intent, sources)
    resp = llm.complete(
        system=_FOUNDATION_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
        tools=[],
    )
    return _parse_foundation_json(resp.text)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_research_synthesis.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/research.py tests/test_research_synthesis.py
git commit -m "feat(research): synthesize_foundation structured LLM step"
```

---

## Task 8: `research_topic` orchestrator (keystone)

**Files:**
- Modify: `src/adaptive_academy/engine/research.py`
- Test: `tests/test_research_orchestrator.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_research_orchestrator.py`:

```python
import json

from sqlmodel import Session, select

from adaptive_academy.engine.research import ResearchResult, research_topic
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import AgentEvent, SourceDoc, Topic, TopicFoundation, TopicIntent


def _topic_with_intent(session: Session) -> tuple[Topic, TopicIntent]:
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="learn transformers", prior_knowledge="strong", time_budget="10h")
    session.add(intent)
    session.commit()
    return topic, intent


def _foundation_llm() -> ScriptedLLMClient:
    payload = json.dumps({"overview": "o", "key_concepts": ["self-attention"], "prerequisite_map": {}})
    return ScriptedLLMClient([LLMResponse(text=payload)])


def _researcher() -> ScriptedResearcherClient:
    # foundational_papers surfaces a duplicate of the canonical_tutorials url to exercise dedup
    return ScriptedResearcherClient(
        {
            "foundational_papers": [
                RawSource(title="Attention", url="https://arxiv.org/abs/1706.03762", tier=1, relevance=0.95, summary="s"),
                RawSource(title="Dup", url="http://www.arxiv.org/abs/1706.03762/", tier=1, relevance=0.5),
            ],
            "canonical_tutorials": [
                RawSource(title="Karpathy", url="https://youtube.com/watch?v=kCc8FmEb1nY", tier=2, relevance=0.8, summary="s"),
            ],
            "key_concepts": [],
            "reference_implementations": [],
            "critiques": [],
        }
    )


def test_research_topic_persists_and_traces(session: Session):
    topic, intent = _topic_with_intent(session)
    result = research_topic(session, topic, intent, researcher=_researcher(), llm=_foundation_llm(), max_subagents=5)

    assert isinstance(result, ResearchResult)

    # Sources: 3 surfaced, 1 duplicate removed -> 2 persisted, all proposed
    sources = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic.id)).all()
    assert len(sources) == 2
    assert {s.status for s in sources} == {"proposed"}
    # ranked: arxiv (tier1) before youtube (tier2)
    ordered = sorted(sources, key=lambda s: s.rank)
    assert "arxiv" in ordered[0].url
    assert ordered[0].rank == 0 and ordered[1].rank == 1
    assert ordered[0].angle == "foundational_papers"

    # Foundation persisted
    fnd = session.exec(select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)).one()
    assert fnd.key_concepts == ["self-attention"]

    # Trace: one subagent event per brief (5), all topic-scoped
    events = session.exec(select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()
    subagent = [e for e in events if e.kind == "research:subagent"]
    assert len(subagent) == 5
    assert all(e.conversation_id is None for e in events)
    assert any(e.kind == "research:done" for e in events)


def test_research_topic_caps_reading_list_and_logs_drop(session: Session):
    topic, intent = _topic_with_intent(session)
    many = [RawSource(title=f"S{i}", url=f"https://s{i}.com", tier=1, relevance=0.9) for i in range(20)]
    researcher = ScriptedResearcherClient({"foundational_papers": many})
    research_topic(session, topic, intent, researcher=researcher, llm=_foundation_llm(), max_subagents=1, cap=12)

    sources = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic.id)).all()
    assert len(sources) == 12  # capped
    events = session.exec(select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()
    assert any(e.kind == "research:capped" for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_research_orchestrator.py -q`
Expected: FAIL — `ImportError` (`ResearchResult`, `research_topic`).

- [ ] **Step 3: Add to `src/adaptive_academy/engine/research.py`**

Add imports at the top (extend the import block):

```python
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlmodel import Session

from adaptive_academy.llm.researcher_types import RawSource, ResearcherClient, SearchBrief
from adaptive_academy.models import AgentEvent, SourceDoc, Topic, TopicFoundation, TopicIntent
```

Add the result dataclass and orchestrator:

```python
@dataclass
class ResearchResult:
    foundation: TopicFoundation
    sources: list[SourceDoc]
    events: list[AgentEvent]


def research_topic(
    session: Session,
    topic: Topic,
    intent: TopicIntent,
    *,
    researcher: ResearcherClient,
    llm: LLMClient,
    max_subagents: int = 5,
    cap: int = 12,
    max_workers: int = 5,
) -> ResearchResult:
    """Fan out over briefs, dedupe+rank, synthesize a foundation, persist, and trace."""
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    briefs = build_briefs(topic.title, intent.goal, max_subagents)
    emit("research:plan", f"{len(briefs)} briefs")

    # Fan out concurrently; collect per-brief results in brief order for deterministic tracing.
    per_brief: list[list[RawSource]] = [[] for _ in briefs]
    if briefs:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(briefs)))) as ex:
            futures = {ex.submit(researcher.search, b): i for i, b in enumerate(briefs)}
            for fut in as_completed(futures):
                per_brief[futures[fut]] = fut.result()

    raw: list[RawSource] = []
    for i, brief in enumerate(briefs):
        found = per_brief[i]
        for s in found:
            s.angle = brief.angle
        emit("research:subagent", f"{brief.angle}: {len(found)} sources")
        raw.extend(found)

    deduped = dedupe_by_url(raw)
    ranked = rank_sources(deduped)
    kept, dropped = ranked[:cap], ranked[cap:]
    if dropped:
        emit("research:capped", f"dropped {len(dropped)} of {len(ranked)}")

    foundation_data = synthesize_foundation(topic.title, intent.goal, kept, llm)
    emit("research:synth", f"{len(foundation_data.key_concepts)} key concepts")

    source_rows: list[SourceDoc] = []
    for idx, s in enumerate(kept):
        row = SourceDoc(
            topic_id=topic.id,
            title=s.title,
            url=s.url,
            tier=s.tier,
            summary=s.summary,
            why=s.why,
            relevance=s.relevance,
            rank=idx,
            angle=s.angle,
            status="proposed",
        )
        session.add(row)
        source_rows.append(row)

    foundation = TopicFoundation(
        topic_id=topic.id,
        overview=foundation_data.overview,
        key_concepts=foundation_data.key_concepts,
        prerequisite_map=foundation_data.prerequisite_map,
    )
    session.add(foundation)
    emit("research:done", f"{len(source_rows)} sources proposed")
    session.commit()

    for row in source_rows:
        session.refresh(row)
    session.refresh(foundation)
    return ResearchResult(foundation=foundation, sources=source_rows, events=events)
```

- [ ] **Step 4: Run the full research suite to verify it passes**

Run: `uv run pytest tests/test_research_orchestrator.py -q`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/research.py tests/test_research_orchestrator.py
git commit -m "feat(research): research_topic fan-out orchestrator with observable trace"
```

---

## Task 9: `AnthropicResearcherClient` (real web-search subagent)

**Files:**
- Create: `src/adaptive_academy/llm/anthropic_researcher.py`
- Test: `tests/test_anthropic_researcher_parse.py` (create — parsing only, no network)

> **Note:** the live network path is NOT unit-tested (mirrors Plan 1's `AnthropicLLMClient`). We test only the pure JSON-extraction helper so the parsing contract is pinned.

- [ ] **Step 1: Write the failing test**

Create `tests/test_anthropic_researcher_parse.py`:

```python
from adaptive_academy.llm.anthropic_researcher import parse_sources_json


def test_parse_sources_json_plain():
    text = '[{"title":"A","url":"https://a.com","tier":1,"summary":"s","why":"w","relevance":0.9}]'
    out = parse_sources_json(text)
    assert len(out) == 1
    assert out[0].title == "A"
    assert out[0].tier == 1
    assert out[0].relevance == 0.9


def test_parse_sources_json_with_fence_and_missing_fields():
    text = '```json\n[{"title":"B","url":"https://b.com"}]\n```'
    out = parse_sources_json(text)
    assert out[0].tier == 3  # default
    assert out[0].relevance == 0.0


def test_parse_sources_json_garbage_returns_empty():
    assert parse_sources_json("not json at all") == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_anthropic_researcher_parse.py -q`
Expected: FAIL — `ModuleNotFoundError`.

- [ ] **Step 3: Create `src/adaptive_academy/llm/anthropic_researcher.py`**

```python
import json
import os

from anthropic import Anthropic

from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.researcher_types import RawSource, SearchBrief

_SYSTEM = (
    "You are a research subagent. Use web search to find the best foundational sources "
    "for the given brief. Return ONLY a JSON array; each element has keys: title, url, "
    "tier (1=authoritative/seminal, 2=synthesis/course, 3=supporting), summary (one "
    "sentence), why (one sentence on why it belongs in a learner's reading list), "
    "relevance (0..1). No prose outside the JSON array."
)


def parse_sources_json(text: str) -> list[RawSource]:
    """Extract a RawSource list from model text. Returns [] on any parse failure."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
        cleaned = cleaned.strip()
    # Trim to the outermost JSON array if surrounded by stray text.
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[RawSource] = []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict) or not d.get("url"):
            continue
        out.append(
            RawSource(
                title=str(d.get("title", d.get("url"))),
                url=str(d["url"]),
                tier=int(d.get("tier", 3)),
                summary=str(d.get("summary", "")),
                why=str(d.get("why", "")),
                relevance=float(d.get("relevance", 0.0)),
            )
        )
    return out


class AnthropicResearcherClient:
    """Real fan-out subagent: one Anthropic Messages call with the web_search tool."""

    def __init__(self, role: str = "reasoning", max_tokens: int = 2048, max_searches: int = 5):
        self._client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=2)
        self._model = get_model(role)
        self._max_tokens = max_tokens
        self._max_searches = max_searches

    def search(self, brief: SearchBrief) -> list[RawSource]:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=_SYSTEM,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": self._max_searches}],
            messages=[{"role": "user", "content": brief.query}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        sources = parse_sources_json(text)
        for s in sources:
            s.angle = brief.angle
        return sources
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_anthropic_researcher_parse.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/llm/anthropic_researcher.py tests/test_anthropic_researcher_parse.py
git commit -m "feat(llm): AnthropicResearcherClient (web_search) + JSON source parser"
```

---

## Task 10: API schemas

**Files:**
- Modify: `src/adaptive_academy/api/schemas.py`
- Test: covered by Task 13 integration test (no isolated test needed for Pydantic shapes).

- [ ] **Step 1: Add schemas to `src/adaptive_academy/api/schemas.py`**

Append (keep existing `TopicOut`, `ConceptOut`, etc.):

```python
class CreateTopicIn(BaseModel):
    title: str
    goal: str
    prior_knowledge: str = ""
    time_budget: str = ""


class IntentOut(BaseModel):
    goal: str
    prior_knowledge: str
    time_budget: str


class SourceDocOut(BaseModel):
    id: int
    title: str
    url: str
    tier: int
    summary: str
    why: str
    rank: int
    angle: str
    status: str


class FoundationOut(BaseModel):
    overview: str
    key_concepts: list[str]
    prerequisite_map: dict


class ResearchOut(BaseModel):
    foundation: FoundationOut
    sources: list[SourceDocOut]
    events: list[EventOut]


class ReviewSourcesIn(BaseModel):
    accepted_ids: list[int] = []
    pruned_ids: list[int] = []
```

- [ ] **Step 2: Extend `TopicOut`** (add optional fields without breaking existing callers):

Find the existing `class TopicOut(BaseModel):` and add two optional fields:

```python
class TopicOut(BaseModel):
    id: int
    title: str
    concepts: list[ConceptOut]
    intent: Optional[IntentOut] = None
    has_foundation: bool = False
```

Ensure `from typing import Optional` is imported at the top of the file (add if absent).

- [ ] **Step 3: Verify import sanity**

Run: `uv run python -c "import adaptive_academy.api.schemas"`
Expected: no error.

- [ ] **Step 4: Commit**

```bash
git add src/adaptive_academy/api/schemas.py
git commit -m "feat(api): schemas for onboarding, research, sources review"
```

---

## Task 11: `get_researcher` dependency

**Files:**
- Modify: `src/adaptive_academy/api/deps.py`

- [ ] **Step 1: Add to `src/adaptive_academy/api/deps.py`**

Add an import and a provider mirroring `get_llm`:

```python
from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
from adaptive_academy.llm.researcher_types import ResearcherClient


def get_researcher() -> ResearcherClient:
    return AnthropicResearcherClient(role="reasoning")
```

- [ ] **Step 2: Verify import sanity**

Run: `uv run python -c "import adaptive_academy.api.deps"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add src/adaptive_academy/api/deps.py
git commit -m "feat(api): get_researcher dependency"
```

---

## Task 12: Routes — create topic + foundation + extend TopicOut serialization

**Files:**
- Modify: `src/adaptive_academy/api/routes_topics.py`
- Test: `tests/test_api_topics_create.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_topics_create.py`:

```python
from fastapi.testclient import TestClient
from sqlmodel import Session

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_session


def _client(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_create_topic_persists_intent(session: Session):
    client = _client(session)
    r = client.post(
        "/api/topics",
        json={"title": "Diffusion models", "goal": "grok score-based models", "prior_knowledge": "ML", "time_budget": "8h"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Diffusion models"
    assert body["intent"]["goal"] == "grok score-based models"
    assert body["has_foundation"] is False


def test_get_foundation_404_before_research(session: Session):
    client = _client(session)
    tid = client.post("/api/topics", json={"title": "T", "goal": "g"}).json()["id"]
    assert client.get(f"/api/topics/{tid}/foundation").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api_topics_create.py -q`
Expected: FAIL — POST `/api/topics` returns 405 (route not defined).

- [ ] **Step 3: Edit `src/adaptive_academy/api/routes_topics.py`**

Add imports at the top (extend existing):

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_session
from adaptive_academy.api.schemas import (
    CreateTopicIn,
    FoundationOut,
    IntentOut,
    TopicOut,
)
from adaptive_academy.models import Topic, TopicFoundation, TopicIntent
```

Add a helper to serialize a Topic into `TopicOut` (reuse the existing concept-loading logic; factor it if needed). Then add the routes:

```python
def _topic_out(session: Session, topic: Topic) -> TopicOut:
    concepts = _concepts_for(session, topic.id)  # existing helper from Plan 1
    intent = session.exec(select(TopicIntent).where(TopicIntent.topic_id == topic.id)).first()
    has_foundation = (
        session.exec(select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)).first()
        is not None
    )
    return TopicOut(
        id=topic.id,
        title=topic.title,
        concepts=concepts,
        intent=IntentOut(goal=intent.goal, prior_knowledge=intent.prior_knowledge, time_budget=intent.time_budget)
        if intent
        else None,
        has_foundation=has_foundation,
    )


@router.post("", response_model=TopicOut)
def create_topic(body: CreateTopicIn, session: Session = Depends(get_session)) -> TopicOut:
    topic = Topic(title=body.title)
    session.add(topic)
    session.commit()
    session.refresh(topic)
    session.add(
        TopicIntent(
            topic_id=topic.id,
            goal=body.goal,
            prior_knowledge=body.prior_knowledge,
            time_budget=body.time_budget,
        )
    )
    session.commit()
    return _topic_out(session, topic)


@router.get("/{topic_id}/foundation", response_model=FoundationOut)
def get_foundation(topic_id: int, session: Session = Depends(get_session)) -> FoundationOut:
    fnd = session.exec(select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)).first()
    if fnd is None:
        raise HTTPException(status_code=404, detail="no foundation yet")
    return FoundationOut(
        overview=fnd.overview, key_concepts=fnd.key_concepts, prerequisite_map=fnd.prerequisite_map
    )
```

> **Note for implementer:** if the existing GET routes build `TopicOut` inline, refactor them to call `_topic_out` so the `intent`/`has_foundation` fields populate consistently. Confirm `_concepts_for` exists (Plan 1 helper joining Concept→Track on topic_id); if its name differs, use the actual one.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_topics_create.py tests/test_api_conversations.py -q`
Expected: PASS (new tests pass; Plan 1 conversation API still green).

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/api/routes_topics.py tests/test_api_topics_create.py
git commit -m "feat(api): create-topic (onboarding intent) + get-foundation routes"
```

---

## Task 13: Routes — trigger research + sources list/review

**Files:**
- Modify: `src/adaptive_academy/api/routes_topics.py`
- Test: `tests/test_api_research.py` (create)

- [ ] **Step 1: Write the failing test**

Create `tests/test_api_research.py`:

```python
import json

from fastapi.testclient import TestClient
from sqlmodel import Session

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse


def _client(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    payload = json.dumps({"overview": "o", "key_concepts": ["self-attention"], "prerequisite_map": {}})
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([LLMResponse(text=payload)])
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient(
        {
            "foundational_papers": [
                RawSource(title="Attention", url="https://arxiv.org/abs/1706.03762", tier=1, relevance=0.95, summary="s"),
            ],
            "canonical_tutorials": [
                RawSource(title="Karpathy", url="https://youtube.com/watch?v=x", tier=2, relevance=0.8, summary="s"),
            ],
        }
    )
    return TestClient(app)


def test_research_review_roundtrip(session: Session):
    client = _client(session)
    tid = client.post("/api/topics", json={"title": "LLMs", "goal": "learn"}).json()["id"]

    r = client.post(f"/api/topics/{tid}/research")
    assert r.status_code == 200
    body = r.json()
    assert body["foundation"]["key_concepts"] == ["self-attention"]
    assert len(body["sources"]) == 2
    assert any(e["kind"] == "research:subagent" for e in body["events"])

    proposed = client.get(f"/api/topics/{tid}/sources?status=proposed").json()
    assert len(proposed) == 2
    keep_id = proposed[0]["id"]
    prune_id = proposed[1]["id"]

    rev = client.post(
        f"/api/topics/{tid}/sources/review",
        json={"accepted_ids": [keep_id], "pruned_ids": [prune_id]},
    )
    assert rev.status_code == 200
    statuses = {s["id"]: s["status"] for s in rev.json()}
    assert statuses[keep_id] == "accepted"
    assert statuses[prune_id] == "pruned"

    accepted = client.get(f"/api/topics/{tid}/sources?status=accepted").json()
    assert [s["id"] for s in accepted] == [keep_id]


def test_research_404_for_missing_topic(session: Session):
    client = _client(session)
    assert client.post("/api/topics/999/research").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_api_research.py -q`
Expected: FAIL — research/sources routes return 405/404 wrongly (routes not defined).

- [ ] **Step 3: Edit `src/adaptive_academy/api/routes_topics.py`**

Extend imports:

```python
from typing import Optional

from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.api.schemas import (
    EventOut,
    ResearchOut,
    ReviewSourcesIn,
    SourceDocOut,
)
from adaptive_academy.engine.research import research_topic
from adaptive_academy.llm.researcher_types import ResearcherClient
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import AgentEvent, SourceDoc
```

Add a serializer + routes:

```python
def _source_out(s: SourceDoc) -> SourceDocOut:
    return SourceDocOut(
        id=s.id, title=s.title, url=s.url, tier=s.tier, summary=s.summary,
        why=s.why, rank=s.rank, angle=s.angle, status=s.status,
    )


@router.post("/{topic_id}/research", response_model=ResearchOut)
def run_research(
    topic_id: int,
    session: Session = Depends(get_session),
    researcher: ResearcherClient = Depends(get_researcher),
    llm: LLMClient = Depends(get_llm),
) -> ResearchOut:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="topic not found")
    intent = session.exec(select(TopicIntent).where(TopicIntent.topic_id == topic_id)).first()
    if intent is None:
        raise HTTPException(status_code=400, detail="topic has no intent")

    result = research_topic(session, topic, intent, researcher=researcher, llm=llm)
    return ResearchOut(
        foundation=FoundationOut(
            overview=result.foundation.overview,
            key_concepts=result.foundation.key_concepts,
            prerequisite_map=result.foundation.prerequisite_map,
        ),
        sources=[_source_out(s) for s in sorted(result.sources, key=lambda x: x.rank)],
        events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events],
    )


@router.get("/{topic_id}/sources", response_model=list[SourceDocOut])
def list_sources(
    topic_id: int,
    status: Optional[str] = None,
    session: Session = Depends(get_session),
) -> list[SourceDocOut]:
    query = select(SourceDoc).where(SourceDoc.topic_id == topic_id)
    if status is not None:
        query = query.where(SourceDoc.status == status)
    rows = session.exec(query).all()
    rows.sort(key=lambda s: s.rank)
    return [_source_out(s) for s in rows]


@router.post("/{topic_id}/sources/review", response_model=list[SourceDocOut])
def review_sources(
    topic_id: int,
    body: ReviewSourcesIn,
    session: Session = Depends(get_session),
) -> list[SourceDocOut]:
    rows = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic_id)).all()
    by_id = {s.id: s for s in rows}
    for sid in body.accepted_ids:
        if sid in by_id:
            by_id[sid].status = "accepted"
    for sid in body.pruned_ids:
        if sid in by_id:
            by_id[sid].status = "pruned"
    session.commit()
    for s in rows:
        session.refresh(s)
    rows.sort(key=lambda s: s.rank)
    return [_source_out(s) for s in rows]
```

> **Implementer note:** `Topic`, `TopicIntent`, `FoundationOut`, `select` are imported in Task 12 — ensure all imports are merged (no duplicates). `FoundationOut` is used here too.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_research.py -q`
Expected: PASS (both tests).

- [ ] **Step 5: Run the full backend suite (regression gate)**

Run: `uv run pytest -q`
Expected: ALL pass (Plan 1 + Plan 2 backend tests).

- [ ] **Step 6: Commit**

```bash
git add src/adaptive_academy/api/routes_topics.py tests/test_api_research.py
git commit -m "feat(api): trigger research + list/review sources routes"
```

---

## Task 14: Frontend — types + api client + vitest

**Files:**
- Modify: `frontend/src/lib/types.ts`
- Modify: `frontend/src/lib/api.ts`
- Modify: `frontend/src/lib/api.test.ts`

- [ ] **Step 1: Add types to `frontend/src/lib/types.ts`**

Append:

```typescript
export interface Intent { goal: string; prior_knowledge: string; time_budget: string; }
export interface SourceDoc {
  id: number; title: string; url: string; tier: number;
  summary: string; why: string; rank: number; angle: string; status: string;
}
export interface Foundation { overview: string; key_concepts: string[]; prerequisite_map: Record<string, string[]>; }
export interface ResearchResult { foundation: Foundation; sources: SourceDoc[]; events: EventOut[]; }
export interface CreateTopicBody { title: string; goal: string; prior_knowledge?: string; time_budget?: string; }
```

(Reuse existing `EventOut`, `Topic`.)

- [ ] **Step 2: Add client calls to `frontend/src/lib/api.ts`**

Add inside the `api` object (follow the existing `j<T>` + fetch pattern):

```typescript
  createTopic: (body: CreateTopicBody) =>
    fetch('/api/topics', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }).then(j<Topic>),
  runResearch: (topicId: number) =>
    fetch(`/api/topics/${topicId}/research`, { method: 'POST' }).then(j<ResearchResult>),
  listSources: (topicId: number, status?: string) =>
    fetch(`/api/topics/${topicId}/sources${status ? `?status=${status}` : ''}`).then(j<SourceDoc[]>),
  reviewSources: (topicId: number, accepted_ids: number[], pruned_ids: number[]) =>
    fetch(`/api/topics/${topicId}/sources/review`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ accepted_ids, pruned_ids })
    }).then(j<SourceDoc[]>)
```

Update the import line at the top of `api.ts` to include the new types:
`import type { Topic, Conversation, SendResult, CreateTopicBody, ResearchResult, SourceDoc } from './types';`
(merge with whatever is already imported).

- [ ] **Step 3: Add a vitest case to `frontend/src/lib/api.test.ts`**

Append a test (follow the existing global.fetch mock style):

```typescript
import { describe, it, expect, vi } from 'vitest';
import { api } from './api';

describe('research api client', () => {
  it('createTopic posts intent and returns topic', async () => {
    const topic = { id: 1, title: 'LLMs', concepts: [] };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => topic }) as any;
    const out = await api.createTopic({ title: 'LLMs', goal: 'learn' });
    expect(out.id).toBe(1);
    expect((global.fetch as any).mock.calls[0][0]).toBe('/api/topics');
    expect((global.fetch as any).mock.calls[0][1].method).toBe('POST');
  });

  it('reviewSources posts accepted/pruned ids', async () => {
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => [] }) as any;
    await api.reviewSources(3, [1], [2]);
    const [url, opts] = (global.fetch as any).mock.calls[0];
    expect(url).toBe('/api/topics/3/sources/review');
    expect(JSON.parse(opts.body)).toEqual({ accepted_ids: [1], pruned_ids: [2] });
  });
});
```

- [ ] **Step 4: Run the frontend tests**

Run: `cd frontend && npm test`
Expected: PASS (existing + new).

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/lib/api.test.ts
git commit -m "feat(frontend): research api client + types + vitest"
```

---

## Task 15: Frontend — `/topics/new` onboarding page

**Files:**
- Create: `frontend/src/routes/topics/new/+page.svelte`

- [ ] **Step 1: Create `frontend/src/routes/topics/new/+page.svelte`**

```svelte
<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';

  let title = $state('');
  let goal = $state('');
  let prior_knowledge = $state('');
  let time_budget = $state('');
  let busy = $state(false);
  let status = $state('');

  async function start() {
    if (!title.trim() || !goal.trim() || busy) return;
    busy = true;
    status = 'Creating topic…';
    try {
      const topic = await api.createTopic({ title, goal, prior_knowledge, time_budget });
      status = 'Researching foundational sources… (this can take a moment)';
      await api.runResearch(topic.id);
      await goto(`/topics/${topic.id}/review`);
    } catch (e) {
      status = 'Something went wrong: ' + (e as Error).message;
      busy = false;
    }
  }
</script>

<main class="mx-auto max-w-2xl p-6 flex flex-col gap-4">
  <h1 class="text-xl font-semibold">New topic</h1>
  <p class="text-sm text-gray-500">A quick brainstorm. The Researcher will gather foundational sources you can review.</p>

  <label class="flex flex-col gap-1">
    <span class="text-sm font-medium">What do you want to learn?</span>
    <input class="border rounded px-3 py-2" bind:value={title} placeholder="e.g. Build LLMs from scratch" disabled={busy} />
  </label>
  <label class="flex flex-col gap-1">
    <span class="text-sm font-medium">Your goal</span>
    <textarea class="border rounded px-3 py-2" bind:value={goal} placeholder="What does 'done' look like?" disabled={busy}></textarea>
  </label>
  <label class="flex flex-col gap-1">
    <span class="text-sm font-medium">Prior knowledge</span>
    <textarea class="border rounded px-3 py-2" bind:value={prior_knowledge} placeholder="What do you already know?" disabled={busy}></textarea>
  </label>
  <label class="flex flex-col gap-1">
    <span class="text-sm font-medium">Time budget</span>
    <input class="border rounded px-3 py-2" bind:value={time_budget} placeholder="e.g. ~10 hrs/week" disabled={busy} />
  </label>

  <button class="bg-black text-white rounded px-4 py-2 disabled:opacity-50" onclick={start} disabled={busy || !title.trim() || !goal.trim()}>
    {busy ? 'Working…' : 'Research this topic'}
  </button>
  {#if status}<p class="text-sm text-gray-600">{status}</p>{/if}
</main>
```

- [ ] **Step 2: Verify the build compiles**

Run: `cd frontend && npm run build`
Expected: build succeeds (no Svelte/TS errors). (If `npm run build` is slow/unavailable, run `npx svelte-check` instead.)

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/topics/new/+page.svelte
git commit -m "feat(frontend): /topics/new onboarding + research trigger"
```

---

## Task 16: Frontend — `/topics/[id]/review` page + nav link

**Files:**
- Create: `frontend/src/routes/topics/[id]/review/+page.svelte`
- Modify: `frontend/src/routes/+page.svelte` (add a "New topic" link)

- [ ] **Step 1: Create `frontend/src/routes/topics/[id]/review/+page.svelte`**

```svelte
<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { SourceDoc, Foundation } from '$lib/types';

  const topicId = Number($page.params.id);
  let foundation = $state<Foundation | null>(null);
  let sources = $state<SourceDoc[]>([]);
  let keep = $state<Record<number, boolean>>({});
  let busy = $state(false);
  let saved = $state(false);

  onMount(async () => {
    try {
      foundation = await api.getFoundation(topicId);
    } catch { foundation = null; }
    sources = await api.listSources(topicId, 'proposed');
    for (const s of sources) keep[s.id] = true;
  });

  async function save() {
    busy = true;
    const accepted = sources.filter((s) => keep[s.id]).map((s) => s.id);
    const pruned = sources.filter((s) => !keep[s.id]).map((s) => s.id);
    try {
      await api.reviewSources(topicId, accepted, pruned);
      saved = true;
    } finally {
      busy = false;
    }
  }
</script>

<main class="mx-auto max-w-3xl p-6 flex flex-col gap-4">
  <h1 class="text-xl font-semibold">Review reading list</h1>

  {#if foundation}
    <section class="border rounded p-4 bg-gray-50">
      <p class="text-sm">{foundation.overview}</p>
      {#if foundation.key_concepts.length}
        <div class="mt-2 flex flex-wrap gap-1">
          {#each foundation.key_concepts as c}
            <span class="text-xs bg-gray-200 rounded px-2 py-0.5">{c}</span>
          {/each}
        </div>
      {/if}
    </section>
  {/if}

  {#if saved}
    <p class="text-green-700 text-sm">Reading list saved.</p>
  {/if}

  <ul class="flex flex-col gap-2">
    {#each sources as s (s.id)}
      <li class="border rounded p-3 flex gap-3 items-start">
        <input type="checkbox" class="mt-1" bind:checked={keep[s.id]} />
        <div class="flex flex-col gap-1">
          <a href={s.url} target="_blank" rel="noreferrer" class="font-medium underline">{s.title}</a>
          <div class="text-xs text-gray-500">tier {s.tier} · {s.angle}</div>
          {#if s.summary}<p class="text-sm">{s.summary}</p>{/if}
          {#if s.why}<p class="text-sm text-gray-600">Why: {s.why}</p>{/if}
        </div>
      </li>
    {/each}
  </ul>

  <button class="bg-black text-white rounded px-4 py-2 disabled:opacity-50 self-start" onclick={save} disabled={busy || !sources.length}>
    {busy ? 'Saving…' : 'Save reading list'}
  </button>
</main>
```

- [ ] **Step 2: Add `getFoundation` to the api client**

In `frontend/src/lib/api.ts`, add inside the `api` object:

```typescript
  getFoundation: (topicId: number) =>
    fetch(`/api/topics/${topicId}/foundation`).then(j<Foundation>),
```

And ensure `Foundation` is in the `import type { ... }` line.

- [ ] **Step 3: Add a nav link in `frontend/src/routes/+page.svelte`**

Near the top of the page's markup (e.g., above the chat header), add:

```svelte
<a href="/topics/new" class="text-sm underline text-gray-600">+ New topic</a>
```

- [ ] **Step 4: Verify build + tests**

Run: `cd frontend && npm run build && npm test`
Expected: build succeeds; vitest passes.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/routes/topics/ frontend/src/lib/api.ts frontend/src/routes/+page.svelte
git commit -m "feat(frontend): source review/prune page + new-topic nav"
```

---

## Task 17: Final regression + manual smoke notes

**Files:** none (verification only)

- [ ] **Step 1: Full backend suite**

Run: `uv run pytest -q`
Expected: all green (Plan 1 + all Plan 2 backend tests).

- [ ] **Step 2: Full frontend suite + build**

Run: `cd frontend && npm test && npm run build`
Expected: green.

- [ ] **Step 3: Confirm seeded path + migration coexist**

```bash
rm -f adaptive_academy.db
uv run alembic upgrade head
uv run aa seed
uv run python -c "from sqlmodel import Session, select; from adaptive_academy.db import engine; from adaptive_academy.models import Topic; s=Session(engine); print([t.title for t in s.exec(select(Topic)).all()])"
```

Expected: prints the seeded topic title; no errors (seed still works on the migrated schema).

- [ ] **Step 4: Record manual smoke steps in the commit message** (live LLM path is hand-tested by the user later):

```
Manual smoke (requires real ANTHROPIC_API_KEY):
  just api  &&  just frontend
  visit /topics/new → fill brainstorm → Research → review/prune → Save
```

No commit needed unless verification surfaced fixes.

---

## Self-Review (completed during planning)

- **Spec coverage:** onboarding intake (Task 12) ✓; fan-out + dedup + rank + persist (Tasks 4–8) ✓; review/prune (Task 13) ✓; observable trace one-event-per-subagent (Task 8 test) ✓; new tables + migration + seeded path intact (Tasks 1, 2, 17) ✓; scripted-client orchestration test + deterministic dedup/rank tests (Tasks 5, 6, 8) ✓.
- **Out-of-scope held:** no CurriculumDirector/Track, no Assessor/SRS, no markdown round-trip, no conversational onboarding, no live-LLM tests.
- **Type consistency:** `RawSource`/`SourceDoc`/`SourceDocOut` field names align; `Foundation` (dataclass) → `TopicFoundation` (table) → `FoundationOut` (schema) keys match (`overview`, `key_concepts`, `prerequisite_map`); `ResearcherClient.search(SearchBrief)->list[RawSource]` used identically in scripted/real/orchestrator; `research_topic` signature matches both its test and the route caller.
- **Determinism:** parallel fan-out results re-ordered into brief order before tracing; dedup/rank pure with total tiebreaks.
```
