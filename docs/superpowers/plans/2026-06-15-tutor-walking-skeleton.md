# Generation-First Tutor Walking Skeleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up a runnable, end-to-end Adaptive Academy slice you can open in a browser and have a multi-turn, generation-first Tutor conversation with, against a hand-seeded Topic/Track, proving the plumbing + orchestration spine + initial UI.

**Architecture:** Python modular monolith (FastAPI + SQLModel + SQLite/WAL) mirroring the sibling `hybrid-coach` repo, with a SvelteKit frontend. The orchestration spine = a tool-tiered conversation engine driving a single **Tutor** agent. Two adaptive levers (`assistance_level`, `challenge_level`) are computed from a per-concept `KnowledgeEstimate` and threaded into the Tutor's system prompt. The **attempt-gate is enforced in code**: a `reveal_solution` tool is blocked by the engine until the learner has logged an attempt, making generation-first a deterministic, testable invariant rather than a prompt suggestion.

**Tech Stack:** Python 3.12, `uv`, FastAPI, SQLModel, SQLite (WAL), Alembic (batch mode), Anthropic SDK (sync client, non-streaming), pytest; SvelteKit 2 / Svelte 5 / Tailwind 4, Vitest, `just`.

**Companion docs:**
- Spec: `docs/superpowers/specs/2026-06-15-adaptive-academy-redesign.md`
- Evidence: `docs/research/2026-06-15-learning-science-evidence.md`

**Conventions used throughout this plan (defined once, reused):**
- Package root: `src/adaptive_academy/`
- `Level` values are the strings `"low" | "medium" | "high"`.
- Message `role` values are `"user" | "tutor"`.
- `compute_levels(estimate)` returns a `Levels(assistance: str, challenge: str)`.
- LLM abstraction: `LLMClient.complete(system, messages, tools) -> LLMResponse`, where
  `LLMResponse(text: str, tool_calls: list[ToolCall])` and `ToolCall(id, name, input)`.
- Tutor tools: `log_attempt(summary)` (auto-tier) and `reveal_solution(text)` (gated-tier).
- The engine entry point is `run_tutor_turn(session, conversation, user_text, llm) -> TurnResult`.

---

## Scope note: the "Orchestrator" in a single-agent skeleton

The spec's **Orchestrator** owns session state, computes the two levers, and *routes
intent to the right agent*. In this skeleton there is exactly one agent (the Tutor), so
**routing is a no-op** and the Orchestrator's remaining responsibilities — owning the
conversation and computing `assistance`/`challenge` levels — live in the conversations
route + the engine (`compute_levels` + `run_tutor_turn`). When the Researcher /
CurriculumDirector / Assessor land, a dedicated `engine/orchestrator.py` extracts that
routing layer. This is intentional; the lever computation and session ownership it would
own already exist and are tested.

## File structure (locked before tasks)

```
adaptive-academy/
├── pyproject.toml                      # uv project, deps, pytest/ruff config
├── justfile                            # dev commands
├── .env.example                        # ANTHROPIC_API_KEY
├── alembic.ini  alembic/               # migrations (batch mode)
├── src/adaptive_academy/
│   ├── __init__.py
│   ├── settings.py                     # env-driven settings
│   ├── db.py                           # engine (SQLite/WAL) + session
│   ├── models.py                       # Topic, Track, Concept, KnowledgeEstimate,
│   │                                   #   Conversation, Message, AgentEvent
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── registry.py                 # model id per role
│   │   ├── types.py                    # ToolCall, LLMResponse, LLMClient protocol
│   │   ├── anthropic_client.py         # AnthropicLLMClient (sync, non-streaming)
│   │   └── scripted_client.py          # ScriptedLLMClient (tests)
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── levels.py                   # compute_levels()
│   │   ├── prompts.py                  # build_tutor_system_prompt()
│   │   ├── tools.py                    # tool schemas + tier table
│   │   └── tutor.py                    # run_tutor_turn() (tool loop + attempt-gate)
│   ├── api/
│   │   ├── __init__.py
│   │   ├── app.py                      # FastAPI factory + CORS + health
│   │   ├── deps.py                     # get_session, get_llm
│   │   ├── schemas.py                  # request/response models
│   │   ├── routes_topics.py
│   │   └── routes_conversations.py
│   ├── seed.py                         # seed Topic/Track/Concepts/estimates
│   └── cli.py                          # `aa seed`, `aa serve`
├── tests/
│   ├── conftest.py                     # in-memory db + client fixtures
│   ├── test_levels.py
│   ├── test_models.py
│   ├── test_tutor_engine.py
│   └── test_api_conversations.py
└── frontend/                           # SvelteKit (see Task 14)
    ├── package.json  svelte.config.js  vite.config.ts
    └── src/
        ├── app.css
        ├── lib/api.ts                  # typed API client
        ├── lib/types.ts
        └── routes/+page.svelte         # Tutor chat
```

---

## Task 0: Reset the repo to greenfield (preserve old code in history)

**Files:**
- Modify: repo root (remove legacy app dirs; the new structure is created in later tasks)

- [ ] **Step 1: Create a working branch**

```bash
git checkout -b redesign/walking-skeleton
```

- [ ] **Step 2: Tag the current state so legacy code is recoverable**

```bash
git tag legacy-v0 -m "Pre-redesign state (AutoGen + BAML + placeholder UIs)"
```

- [ ] **Step 3: Remove legacy application dirs from the working tree (history retains them)**

```bash
git rm -r --quiet backend baml_src baml_client shared frontend dashboard \
  scripts tests MVP_EXECUTION_PLAN.md package.json pyproject.toml uv.lock \
  justfile README.md 2>/dev/null; true
```

Note: `docs/` is intentionally kept (spec + evidence + this plan). If any path above
does not exist, the `; true` keeps the step from failing.

- [ ] **Step 4: Commit the reset**

```bash
git add -A && git commit -m "chore: reset to greenfield; legacy preserved at tag legacy-v0"
```

---

## Task 1: Project scaffold (uv, deps, config, justfile)

**Files:**
- Create: `pyproject.toml`, `.env.example`, `justfile`, `src/adaptive_academy/__init__.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[project]
name = "adaptive-academy"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "sqlmodel>=0.0.22",
    "alembic>=1.13",
    "anthropic>=0.40",
    "pydantic-settings>=2.5",
    "python-dotenv>=1.0",
]

[dependency-groups]
dev = ["pytest>=8.3", "httpx>=0.27", "ruff>=0.7"]

[project.scripts]
aa = "adaptive_academy.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/adaptive_academy"]

[tool.pytest.ini_options]
pythonpath = ["src"]
testpaths = ["tests"]

[tool.ruff]
line-length = 100
src = ["src", "tests"]
```

- [ ] **Step 2: Create `.env.example`**

```bash
ANTHROPIC_API_KEY=sk-ant-xxxxx
AA_DATABASE_URL=sqlite:///./adaptive_academy.db
```

- [ ] **Step 3: Create `src/adaptive_academy/__init__.py`**

```python
__version__ = "0.1.0"
```

- [ ] **Step 4: Create `justfile`**

```make
set dotenv-load := true

install:
    uv sync

seed:
    uv run aa seed

api:
    uv run uvicorn adaptive_academy.api.app:app --reload --port 8000

frontend:
    cd frontend && npm run dev

test:
    uv run pytest -q
```

- [ ] **Step 5: Install and verify the toolchain**

Run: `uv sync && uv run python -c "import adaptive_academy; print(adaptive_academy.__version__)"`
Expected: prints `0.1.0`

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .env.example justfile src/adaptive_academy/__init__.py
git commit -m "chore: scaffold uv project, deps, justfile"
```

---

## Task 2: Settings & database (SQLite + WAL)

**Files:**
- Create: `src/adaptive_academy/settings.py`, `src/adaptive_academy/db.py`

- [ ] **Step 1: Create `src/adaptive_academy/settings.py`**

```python
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="AA_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./adaptive_academy.db"


settings = Settings()
```

- [ ] **Step 2: Create `src/adaptive_academy/db.py`**

```python
from collections.abc import Iterator

from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine

from adaptive_academy.settings import settings

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
)


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
```

- [ ] **Step 3: Commit**

```bash
git add src/adaptive_academy/settings.py src/adaptive_academy/db.py
git commit -m "feat: settings + sqlite engine with WAL"
```

---

## Task 3: Data model

**Files:**
- Create: `src/adaptive_academy/models.py`
- Test: `tests/test_models.py`, `tests/conftest.py`

- [ ] **Step 1: Create `tests/conftest.py`**

```python
import pytest
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
```

- [ ] **Step 2: Write the failing test `tests/test_models.py`**

```python
from adaptive_academy.models import (
    Concept,
    Conversation,
    KnowledgeEstimate,
    Message,
    Topic,
    Track,
)


def test_topic_track_concept_estimate_roundtrip(session):
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()

    track = Track(topic_id=topic.id, title="Core track")
    session.add(track)
    session.commit()

    concept = Concept(track_id=track.id, name="self-attention", is_load_bearing=True)
    session.add(concept)
    session.commit()

    est = KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6)
    session.add(est)
    session.commit()

    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()
    session.add(Message(conversation_id=convo.id, role="user", content="hi"))
    session.commit()

    assert concept.estimate.level == "high"
    assert convo.messages[0].content == "hi"
    assert convo.attempt_logged is False
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_models.py -q`
Expected: FAIL with `ModuleNotFoundError: adaptive_academy.models`

- [ ] **Step 4: Create `src/adaptive_academy/models.py`**

```python
from datetime import datetime, timezone
from typing import Optional

from sqlmodel import Field, Relationship, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Topic(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    created_at: datetime = Field(default_factory=_now)
    tracks: list["Track"] = Relationship(back_populates="topic")


class Track(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id")
    title: str
    topic: Optional[Topic] = Relationship(back_populates="tracks")
    concepts: list["Concept"] = Relationship(back_populates="track")


class Concept(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    track_id: int = Field(foreign_key="track.id")
    name: str
    is_load_bearing: bool = False
    track: Optional[Track] = Relationship(back_populates="concepts")
    estimate: Optional["KnowledgeEstimate"] = Relationship(back_populates="concept")


class KnowledgeEstimate(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concept.id", unique=True)
    level: str = "high"  # "low" | "medium" | "high"
    confidence: float = 0.5
    updated_at: datetime = Field(default_factory=_now)
    concept: Optional[Concept] = Relationship(back_populates="estimate")


class Conversation(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id")
    concept_id: int = Field(foreign_key="concept.id")
    attempt_logged: bool = False
    created_at: datetime = Field(default_factory=_now)
    messages: list["Message"] = Relationship(
        back_populates="conversation",
        sa_relationship_kwargs={"order_by": "Message.id"},
    )


class Message(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id")
    role: str  # "user" | "tutor"
    content: str
    created_at: datetime = Field(default_factory=_now)
    conversation: Optional[Conversation] = Relationship(back_populates="messages")


class AgentEvent(SQLModel, table=True):
    """Observability trace: one row per engine/agent step."""

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: int = Field(foreign_key="conversation.id")
    kind: str  # e.g. "levels", "llm_call", "tool:log_attempt", "tool:reveal_solution:blocked"
    detail: str = ""
    created_at: datetime = Field(default_factory=_now)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_models.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/adaptive_academy/models.py tests/conftest.py tests/test_models.py
git commit -m "feat: data model (topic/track/concept/estimate/conversation/message/event)"
```

---

## Task 4: Adaptive levers (`compute_levels`)

**Files:**
- Create: `src/adaptive_academy/engine/__init__.py`, `src/adaptive_academy/engine/levels.py`
- Test: `tests/test_levels.py`

- [ ] **Step 1: Write the failing test `tests/test_levels.py`**

```python
from adaptive_academy.engine.levels import Levels, compute_levels
from adaptive_academy.models import KnowledgeEstimate


def _est(level: str) -> KnowledgeEstimate:
    return KnowledgeEstimate(concept_id=1, level=level)


def test_expert_gets_low_assistance_high_challenge():
    assert compute_levels(_est("high")) == Levels(assistance="low", challenge="high")


def test_novice_gets_high_assistance_low_challenge():
    assert compute_levels(_est("low")) == Levels(assistance="high", challenge="low")


def test_medium_is_balanced():
    assert compute_levels(_est("medium")) == Levels(assistance="medium", challenge="medium")


def test_missing_estimate_defaults_to_expert_lean():
    # No estimate yet -> default to low assistance (do no harm to an expert).
    assert compute_levels(None) == Levels(assistance="low", challenge="high")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_levels.py -q`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Create `src/adaptive_academy/engine/__init__.py`**

```python
```

(empty file)

- [ ] **Step 4: Create `src/adaptive_academy/engine/levels.py`**

```python
from dataclasses import dataclass

from adaptive_academy.models import KnowledgeEstimate

# knowledge level -> (assistance, challenge). Expertise-reversal + ZPD:
# more prior knowledge => LESS assistance and MORE challenge.
_MAP = {
    "low": ("high", "low"),
    "medium": ("medium", "medium"),
    "high": ("low", "high"),
}


@dataclass(frozen=True)
class Levels:
    assistance: str  # "low" | "medium" | "high"
    challenge: str  # "low" | "medium" | "high"


def compute_levels(estimate: KnowledgeEstimate | None) -> Levels:
    # Default (no estimate): assume the expert case — do no harm via over-assistance.
    level = estimate.level if estimate is not None else "high"
    assistance, challenge = _MAP.get(level, ("low", "high"))
    return Levels(assistance=assistance, challenge=challenge)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `uv run pytest tests/test_levels.py -q`
Expected: PASS (4 passed)

- [ ] **Step 6: Commit**

```bash
git add src/adaptive_academy/engine/__init__.py src/adaptive_academy/engine/levels.py tests/test_levels.py
git commit -m "feat: adaptive levers (assistance + challenge) from knowledge estimate"
```

---

## Task 5: LLM abstraction (types + protocol + scripted fake)

**Files:**
- Create: `src/adaptive_academy/llm/__init__.py`, `src/adaptive_academy/llm/types.py`,
  `src/adaptive_academy/llm/scripted_client.py`, `src/adaptive_academy/llm/registry.py`

- [ ] **Step 1: Create `src/adaptive_academy/llm/__init__.py`**

```python
```

(empty file)

- [ ] **Step 2: Create `src/adaptive_academy/llm/types.py`**

```python
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLMClient(Protocol):
    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...
```

- [ ] **Step 3: Create `src/adaptive_academy/llm/registry.py`**

```python
# Resolve model ids by role, not hardcoded at call sites. Update here on model upgrades.
MODELS = {
    "reasoning": "claude-sonnet-4-6",
    "copy": "claude-haiku-4-5",
}


def get_model(role: str) -> str:
    return MODELS[role]
```

- [ ] **Step 4: Create `src/adaptive_academy/llm/scripted_client.py`**

```python
from typing import Any

from adaptive_academy.llm.types import LLMResponse


class ScriptedLLMClient:
    """Test double: returns queued LLMResponses in order, recording calls."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, system, messages, tools) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if not self._responses:
            raise AssertionError("ScriptedLLMClient ran out of responses")
        return self._responses.pop(0)
```

- [ ] **Step 5: Verify it imports**

Run: `uv run python -c "from adaptive_academy.llm.scripted_client import ScriptedLLMClient; print('ok')"`
Expected: prints `ok`

- [ ] **Step 6: Commit**

```bash
git add src/adaptive_academy/llm/__init__.py src/adaptive_academy/llm/types.py \
  src/adaptive_academy/llm/registry.py src/adaptive_academy/llm/scripted_client.py
git commit -m "feat: llm abstraction (types, registry, scripted test client)"
```

---

## Task 6: Tutor prompt + tool schemas

**Files:**
- Create: `src/adaptive_academy/engine/prompts.py`, `src/adaptive_academy/engine/tools.py`

- [ ] **Step 1: Create `src/adaptive_academy/engine/tools.py`**

```python
# Tool schemas (Anthropic tool-use format) + tier table.
# Tiers: "auto" executes immediately; "gated" is blocked until attempt_logged is True.

LOG_ATTEMPT = {
    "name": "log_attempt",
    "description": (
        "Record that the learner has made a genuine attempt or explanation. "
        "Call this as soon as the learner tries, even partially."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"summary": {"type": "string"}},
        "required": ["summary"],
    },
}

REVEAL_SOLUTION = {
    "name": "reveal_solution",
    "description": (
        "Reveal a full worked solution / final answer. Only permitted AFTER the learner "
        "has logged an attempt. If no attempt has been logged, this call is blocked and "
        "you must give a hint instead."
    ),
    "input_schema": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
}

TOOLS = [LOG_ATTEMPT, REVEAL_SOLUTION]
TIERS = {"log_attempt": "auto", "reveal_solution": "gated"}
```

- [ ] **Step 2: Create `src/adaptive_academy/engine/prompts.py`**

```python
from adaptive_academy.engine.levels import Levels

_BASE = """You are a generation-first tutor for an advanced adult learner. Your job is \
to push understanding, NOT to do the thinking for them.

HARD RULES (non-negotiable):
- Never hand over a full solution or final answer until the learner has made a genuine \
attempt. When they ask for "the answer" before trying, respond with ONE hint or a \
Socratic question and invite an attempt.
- When the learner does attempt or explain, call the log_attempt tool with a short \
summary of what they tried.
- Only call reveal_solution AFTER an attempt is logged. If you call it too early it will \
be blocked and you must give a hint instead.
- Serve the source material: point the learner INTO concepts and ask them to generate, \
recall, or derive. Do not summarize so they can passively consume.
- Do not express confidence you do not have; flag uncertainty.

Concept under study: {concept}

Assistance level = {assistance}: at "low", give minimal nudges and make them work; at \
"high", scaffold more concretely (but still attempt-first).
Challenge level = {challenge}: pitch the next step at this difficulty — at "high", push \
to the edge of their competence; at "low", ease off."""


def build_tutor_system_prompt(concept: str, levels: Levels) -> str:
    return _BASE.format(
        concept=concept, assistance=levels.assistance, challenge=levels.challenge
    )
```

- [ ] **Step 3: Verify import**

Run: `uv run python -c "from adaptive_academy.engine.prompts import build_tutor_system_prompt; from adaptive_academy.engine.levels import Levels; print(build_tutor_system_prompt('self-attention', Levels('low','high'))[:20])"`
Expected: prints `You are a generation`

- [ ] **Step 4: Commit**

```bash
git add src/adaptive_academy/engine/tools.py src/adaptive_academy/engine/prompts.py
git commit -m "feat: tutor system prompt + tool schemas with tiers"
```

---

## Task 7: Tutor engine (tool loop + code-enforced attempt-gate)

**Files:**
- Create: `src/adaptive_academy/engine/tutor.py`
- Test: `tests/test_tutor_engine.py`

- [ ] **Step 1: Write the failing test `tests/test_tutor_engine.py`**

```python
from adaptive_academy.engine.tutor import run_tutor_turn
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse, ToolCall
from adaptive_academy.models import (
    Concept,
    Conversation,
    KnowledgeEstimate,
    Topic,
    Track,
)


def _seed(session) -> Conversation:
    topic = Topic(title="LLMs")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="self-attention")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high"))
    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()
    return convo


def test_reveal_blocked_before_attempt(session):
    convo = _seed(session)
    # Model immediately tries to reveal the solution, then (after the block) gives a hint.
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="reveal_solution",
                                         input={"text": "FULL ANSWER 42"})]),
        LLMResponse(text="Here's a hint: what does softmax normalize over?"),
    ])
    result = run_tutor_turn(session, convo, "just give me the answer", llm)

    assert "FULL ANSWER 42" not in result.reply
    assert "hint" in result.reply.lower()
    assert convo.attempt_logged is False
    assert any("reveal_solution:blocked" in e.kind for e in result.events)


def test_attempt_then_reveal_allowed(session):
    convo = _seed(session)
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="log_attempt",
                                         input={"summary": "tried QK^T"})]),
        LLMResponse(tool_calls=[ToolCall(id="t2", name="reveal_solution",
                                         input={"text": "FULL ANSWER 42"})]),
        LLMResponse(text="Great — the full picture: FULL ANSWER 42"),
    ])
    result = run_tutor_turn(session, convo, "I think attention is softmax(QK^T)V", llm)

    assert convo.attempt_logged is True
    assert "FULL ANSWER 42" in result.reply
    assert any(e.kind == "tool:log_attempt" for e in result.events)


def test_plain_reply_persists_messages(session):
    convo = _seed(session)
    llm = ScriptedLLMClient([LLMResponse(text="What do you already know about it?")])
    result = run_tutor_turn(session, convo, "teach me attention", llm)

    session.refresh(convo)
    roles = [(m.role, m.content) for m in convo.messages]
    assert roles[0] == ("user", "teach me attention")
    assert roles[1] == ("tutor", "What do you already know about it?")
    assert result.reply == "What do you already know about it?"
    # First call should include the computed levels in the system prompt (expert -> low/high)
    assert "Assistance level = low" in llm.calls[0]["system"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tutor_engine.py -q`
Expected: FAIL with `ModuleNotFoundError: adaptive_academy.engine.tutor`

- [ ] **Step 3: Create `src/adaptive_academy/engine/tutor.py`**

```python
from dataclasses import dataclass

from sqlmodel import Session

from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.prompts import build_tutor_system_prompt
from adaptive_academy.engine.tools import TIERS, TOOLS
from adaptive_academy.llm.types import LLMClient, LLMResponse, ToolCall
from adaptive_academy.models import AgentEvent, Concept, Conversation, Message

_MAX_STEPS = 6


@dataclass
class TurnResult:
    reply: str
    events: list[AgentEvent]


def _history(convo: Conversation) -> list[dict]:
    role_map = {"user": "user", "tutor": "assistant"}
    return [{"role": role_map[m.role], "content": m.content} for m in convo.messages]


def run_tutor_turn(
    session: Session,
    convo: Conversation,
    user_text: str,
    llm: LLMClient,
) -> TurnResult:
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(conversation_id=convo.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    # Persist the incoming user message.
    session.add(Message(conversation_id=convo.id, role="user", content=user_text))
    session.commit()
    session.refresh(convo)

    concept = session.get(Concept, convo.concept_id)
    levels = compute_levels(concept.estimate if concept else None)
    emit("levels", f"assistance={levels.assistance} challenge={levels.challenge}")
    system = build_tutor_system_prompt(concept.name if concept else "", levels)

    messages = _history(convo)
    reply_text = ""

    for _ in range(_MAX_STEPS):
        emit("llm_call")
        resp: LLMResponse = llm.complete(system=system, messages=messages, tools=TOOLS)

        if not resp.tool_calls:
            reply_text = resp.text
            break

        # Echo the assistant tool-use turn into the running transcript.
        messages.append({"role": "assistant", "content": _assistant_tool_blocks(resp)})
        tool_results = []
        for call in resp.tool_calls:
            ok, payload = _execute_tool(session, convo, call, emit)
            tool_results.append(
                {"type": "tool_result", "tool_use_id": call.id, "content": payload}
            )
            if call.name == "reveal_solution" and ok:
                reply_text = call.input.get("text", "")
        messages.append({"role": "user", "content": tool_results})

    # Persist the tutor reply.
    session.add(Message(conversation_id=convo.id, role="tutor", content=reply_text))
    session.commit()
    return TurnResult(reply=reply_text, events=events)


def _assistant_tool_blocks(resp: LLMResponse) -> list[dict]:
    blocks: list[dict] = []
    if resp.text:
        blocks.append({"type": "text", "text": resp.text})
    for call in resp.tool_calls:
        blocks.append(
            {"type": "tool_use", "id": call.id, "name": call.name, "input": call.input}
        )
    return blocks


def _execute_tool(session, convo: Conversation, call: ToolCall, emit) -> tuple[bool, str]:
    tier = TIERS.get(call.name, "auto")

    if call.name == "log_attempt":
        convo.attempt_logged = True
        session.add(convo)
        session.commit()
        emit("tool:log_attempt", call.input.get("summary", ""))
        return True, "ok: attempt recorded"

    if call.name == "reveal_solution":
        if tier == "gated" and not convo.attempt_logged:
            emit("tool:reveal_solution:blocked")
            return False, (
                "BLOCKED: the learner has not logged an attempt yet. Do NOT reveal the "
                "solution. Give a single hint or Socratic question instead."
            )
        emit("tool:reveal_solution:allowed")
        return True, "ok: solution permitted"

    emit(f"tool:{call.name}:unknown")
    return False, f"unknown tool {call.name}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_tutor_engine.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/tutor.py tests/test_tutor_engine.py
git commit -m "feat: tutor engine with code-enforced attempt-gate + observability events"
```

---

## Task 8: Anthropic client (real, non-streaming)

**Files:**
- Create: `src/adaptive_academy/llm/anthropic_client.py`

- [ ] **Step 1: Create `src/adaptive_academy/llm/anthropic_client.py`**

```python
import os
from typing import Any

from anthropic import Anthropic

from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.types import LLMResponse, ToolCall


class AnthropicLLMClient:
    """Sync, non-streaming Anthropic client implementing the LLMClient protocol."""

    def __init__(self, role: str = "reasoning", max_tokens: int = 1024):
        self._client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=3)
        self._model = get_model(role)
        self._max_tokens = max_tokens

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
        return LLMResponse(text="".join(text_parts), tool_calls=tool_calls)
```

- [ ] **Step 2: Verify import (no API call)**

Run: `uv run python -c "from adaptive_academy.llm.anthropic_client import AnthropicLLMClient; print('ok')"`
Expected: prints `ok`

- [ ] **Step 3: Commit**

```bash
git add src/adaptive_academy/llm/anthropic_client.py
git commit -m "feat: real anthropic client (sync, non-streaming, tool-use)"
```

---

## Task 9: Seed script + CLI

**Files:**
- Create: `src/adaptive_academy/seed.py`, `src/adaptive_academy/cli.py`

- [ ] **Step 1: Create `src/adaptive_academy/seed.py`**

```python
from sqlmodel import Session, select

from adaptive_academy.db import create_db_and_tables, engine
from adaptive_academy.models import Concept, KnowledgeEstimate, Topic, Track

_CONCEPTS = [
    ("self-attention", True),
    ("backpropagation", True),
    ("tokenization (BPE)", True),
    ("LoRA / low-rank adaptation", False),
]


def seed() -> None:
    create_db_and_tables()
    with Session(engine) as session:
        if session.exec(select(Topic)).first():
            print("Already seeded.")
            return
        topic = Topic(title="Build LLMs from scratch")
        session.add(topic)
        session.commit()
        track = Track(topic_id=topic.id, title="Core track")
        session.add(track)
        session.commit()
        for name, load_bearing in _CONCEPTS:
            concept = Concept(track_id=track.id, name=name, is_load_bearing=load_bearing)
            session.add(concept)
            session.commit()
            session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
        session.commit()
        print(f"Seeded topic {topic.id} with {len(_CONCEPTS)} concepts.")
```

- [ ] **Step 2: Create `src/adaptive_academy/cli.py`**

```python
import sys


def main() -> None:
    cmd = sys.argv[1] if len(sys.argv) > 1 else "help"
    if cmd == "seed":
        from adaptive_academy.seed import seed

        seed()
    else:
        print("usage: aa seed")


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Run the seed and verify**

Run: `uv run aa seed && uv run python -c "from sqlmodel import Session, select; from adaptive_academy.db import engine; from adaptive_academy.models import Concept; s=Session(engine); print(len(s.exec(select(Concept)).all()))"`
Expected: prints `Seeded topic 1 with 4 concepts.` then `4`

- [ ] **Step 4: Commit**

```bash
git add src/adaptive_academy/seed.py src/adaptive_academy/cli.py
git commit -m "feat: seed script + cli (Build LLMs from scratch topic)"
```

---

## Task 10: API schemas + dependencies

**Files:**
- Create: `src/adaptive_academy/api/__init__.py`, `src/adaptive_academy/api/schemas.py`,
  `src/adaptive_academy/api/deps.py`

- [ ] **Step 1: Create `src/adaptive_academy/api/__init__.py`**

```python
```

(empty file)

- [ ] **Step 2: Create `src/adaptive_academy/api/schemas.py`**

```python
from pydantic import BaseModel


class ConceptOut(BaseModel):
    id: int
    name: str
    is_load_bearing: bool


class TopicOut(BaseModel):
    id: int
    title: str
    concepts: list[ConceptOut]


class StartConversationIn(BaseModel):
    topic_id: int
    concept_id: int


class MessageOut(BaseModel):
    role: str
    content: str


class EventOut(BaseModel):
    kind: str
    detail: str


class SendMessageIn(BaseModel):
    content: str


class ConversationOut(BaseModel):
    id: int
    concept_id: int
    attempt_logged: bool
    assistance_level: str
    challenge_level: str
    messages: list[MessageOut]


class SendMessageOut(BaseModel):
    reply: str
    attempt_logged: bool
    assistance_level: str
    challenge_level: str
    events: list[EventOut]
```

- [ ] **Step 3: Create `src/adaptive_academy/api/deps.py`**

```python
from collections.abc import Iterator

from sqlmodel import Session

from adaptive_academy.db import engine
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.types import LLMClient


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session


def get_llm() -> LLMClient:
    return AnthropicLLMClient(role="reasoning")
```

- [ ] **Step 4: Commit**

```bash
git add src/adaptive_academy/api/__init__.py src/adaptive_academy/api/schemas.py src/adaptive_academy/api/deps.py
git commit -m "feat: api schemas + dependencies"
```

---

## Task 11: Topics route

**Files:**
- Create: `src/adaptive_academy/api/routes_topics.py`

- [ ] **Step 1: Create `src/adaptive_academy/api/routes_topics.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_session
from adaptive_academy.api.schemas import ConceptOut, TopicOut
from adaptive_academy.models import Concept, Topic, Track

router = APIRouter(prefix="/api/topics", tags=["topics"])


def _concepts_for(session: Session, topic_id: int) -> list[Concept]:
    return session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)
    ).all()


@router.get("", response_model=list[TopicOut])
def list_topics(session: Session = Depends(get_session)):
    return [
        _to_out(topic, _concepts_for(session, topic.id))
        for topic in session.exec(select(Topic)).all()
    ]


@router.get("/{topic_id}", response_model=TopicOut)
def get_topic(topic_id: int, session: Session = Depends(get_session)):
    topic = session.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "topic not found")
    return _to_out(topic, _concepts_for(session, topic_id))


def _to_out(topic: Topic, concepts: list[Concept]) -> TopicOut:
    return TopicOut(
        id=topic.id,
        title=topic.title,
        concepts=[
            ConceptOut(id=c.id, name=c.name, is_load_bearing=c.is_load_bearing)
            for c in concepts
        ],
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/adaptive_academy/api/routes_topics.py
git commit -m "feat: topics route"
```

---

## Task 12: Conversations route

**Files:**
- Create: `src/adaptive_academy/api/routes_conversations.py`

- [ ] **Step 1: Create `src/adaptive_academy/api/routes_conversations.py`**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import (
    ConversationOut,
    EventOut,
    MessageOut,
    SendMessageIn,
    SendMessageOut,
    StartConversationIn,
)
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.tutor import run_tutor_turn
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Concept, Conversation

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _levels_for(session: Session, convo: Conversation):
    concept = session.get(Concept, convo.concept_id)
    return compute_levels(concept.estimate if concept else None)


@router.post("", response_model=ConversationOut)
def start_conversation(body: StartConversationIn, session: Session = Depends(get_session)):
    convo = Conversation(topic_id=body.topic_id, concept_id=body.concept_id)
    session.add(convo)
    session.commit()
    session.refresh(convo)
    levels = _levels_for(session, convo)
    return ConversationOut(
        id=convo.id,
        concept_id=convo.concept_id,
        attempt_logged=convo.attempt_logged,
        assistance_level=levels.assistance,
        challenge_level=levels.challenge,
        messages=[],
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: int, session: Session = Depends(get_session)):
    convo = session.get(Conversation, conversation_id)
    if not convo:
        raise HTTPException(404, "conversation not found")
    levels = _levels_for(session, convo)
    return ConversationOut(
        id=convo.id,
        concept_id=convo.concept_id,
        attempt_logged=convo.attempt_logged,
        assistance_level=levels.assistance,
        challenge_level=levels.challenge,
        messages=[MessageOut(role=m.role, content=m.content) for m in convo.messages],
    )


@router.post("/{conversation_id}/messages", response_model=SendMessageOut)
def send_message(
    conversation_id: int,
    body: SendMessageIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
):
    convo = session.get(Conversation, conversation_id)
    if not convo:
        raise HTTPException(404, "conversation not found")
    result = run_tutor_turn(session, convo, body.content, llm)
    session.refresh(convo)
    levels = _levels_for(session, convo)
    return SendMessageOut(
        reply=result.reply,
        attempt_logged=convo.attempt_logged,
        assistance_level=levels.assistance,
        challenge_level=levels.challenge,
        events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events],
    )
```

- [ ] **Step 2: Commit**

```bash
git add src/adaptive_academy/api/routes_conversations.py
git commit -m "feat: conversations route (start/get/send)"
```

---

## Task 13: FastAPI app + integration test

**Files:**
- Create: `src/adaptive_academy/api/app.py`
- Test: `tests/test_api_conversations.py`

- [ ] **Step 1: Create `src/adaptive_academy/api/app.py`**

```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from adaptive_academy.api import routes_conversations, routes_topics
from adaptive_academy.db import create_db_and_tables


def create_app() -> FastAPI:
    app = FastAPI(title="Adaptive Academy")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup() -> None:
        create_db_and_tables()

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(routes_topics.router)
    app.include_router(routes_conversations.router)
    return app


app = create_app()
```

- [ ] **Step 2: Write the failing integration test `tests/test_api_conversations.py`**

```python
import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse, ToolCall
from adaptive_academy.models import Concept, Conversation, KnowledgeEstimate, Topic, Track


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        topic = Topic(title="LLMs")
        s.add(topic)
        s.commit()
        track = Track(topic_id=topic.id, title="Core")
        s.add(track)
        s.commit()
        concept = Concept(track_id=track.id, name="self-attention")
        s.add(concept)
        s.commit()
        s.add(KnowledgeEstimate(concept_id=concept.id, level="high"))
        s.commit()
        topic_id, concept_id = topic.id, concept.id

    def _session_override():
        with Session(engine) as s:
            yield s

    scripted = ScriptedLLMClient([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="reveal_solution",
                                         input={"text": "SECRET"})]),
        LLMResponse(text="Hint: what does softmax normalize?"),
    ])

    app = create_app()
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_llm] = lambda: scripted
    c = TestClient(app)
    c.topic_id, c.concept_id = topic_id, concept_id
    return c


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_send_message_blocks_reveal_before_attempt(client):
    start = client.post(
        "/api/conversations",
        json={"topic_id": client.topic_id, "concept_id": client.concept_id},
    ).json()
    assert start["assistance_level"] == "low"
    assert start["challenge_level"] == "high"

    resp = client.post(
        f"/api/conversations/{start['id']}/messages",
        json={"content": "just give me the answer"},
    ).json()

    assert "SECRET" not in resp["reply"]
    assert resp["attempt_logged"] is False
    assert any("reveal_solution:blocked" in e["kind"] for e in resp["events"])
```

- [ ] **Step 3: Run test to verify it fails, then passes**

Run: `uv run pytest tests/test_api_conversations.py -q`
Expected: first run FAILS if `app.py` missing; after Step 1 in place, PASS (2 passed)

- [ ] **Step 4: Run the full suite**

Run: `uv run pytest -q`
Expected: PASS (all tests green)

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/api/app.py tests/test_api_conversations.py
git commit -m "feat: fastapi app + health + conversations integration test"
```

---

## Task 14: Alembic baseline migration

**Files:**
- Create: `alembic.ini`, `alembic/env.py`, `alembic/versions/0001_initial.py` (generated)

- [ ] **Step 1: Initialize alembic**

Run: `uv run alembic init alembic`
Expected: creates `alembic.ini` and `alembic/`

- [ ] **Step 2: Edit `alembic/env.py` to use our metadata + batch mode**

Replace the body of `alembic/env.py` with:

```python
from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

import adaptive_academy.models  # noqa: F401  (register tables)
from adaptive_academy.db import engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = SQLModel.metadata


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite-safe ALTER TABLE
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
```

- [ ] **Step 3: Generate the initial migration**

Run: `uv run alembic revision --autogenerate -m "initial"`
Expected: creates `alembic/versions/XXXX_initial.py` with all tables

- [ ] **Step 4: Apply it to a fresh DB and verify**

Run: `rm -f adaptive_academy.db && uv run alembic upgrade head && uv run aa seed`
Expected: `Seeded topic 1 with 4 concepts.`

- [ ] **Step 5: Commit**

```bash
git add alembic.ini alembic/
git commit -m "feat: alembic baseline migration (batch mode for sqlite)"
```

---

## Task 15: Frontend scaffold (SvelteKit + Tailwind)

**Files:**
- Create: `frontend/` (SvelteKit skeleton), `frontend/src/app.css`, `frontend/vite.config.ts`

- [ ] **Step 1: Scaffold SvelteKit** (from the repo root)

```bash
npx sv create frontend --template minimal --types ts --no-add-ons
cd frontend && npm install && npm install -D tailwindcss @tailwindcss/vite
```

Notes: `sv` is the current SvelteKit CLI (it replaced `npm create svelte`). If `sv`
prompts interactively, choose: **minimal** template, **TypeScript**, **no add-ons**.
This produces Svelte 5 + SvelteKit 2.

- [ ] **Step 2: Configure Tailwind + dev proxy in `frontend/vite.config.ts`**

```typescript
import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: {
    proxy: { '/api': 'http://localhost:8000' }
  }
});
```

- [ ] **Step 3: Create `frontend/src/app.css`**

```css
@import 'tailwindcss';
```

- [ ] **Step 4: Ensure `frontend/src/routes/+layout.svelte` imports the css**

```svelte
<script lang="ts">
  import '../app.css';
  let { children } = $props();
</script>

{@render children()}
```

- [ ] **Step 5: Verify dev server boots**

Run: `cd frontend && npm run dev -- --port 5173 &` then `sleep 3 && curl -s localhost:5173 | head -c 50; kill %1`
Expected: returns HTML (no crash)

- [ ] **Step 6: Commit**

```bash
git add frontend
git commit -m "feat: sveltekit + tailwind scaffold with /api dev proxy"
```

---

## Task 16: Frontend API client + types (with Vitest test)

**Files:**
- Create: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/api.test.ts`

- [ ] **Step 1: Create `frontend/src/lib/types.ts`**

```typescript
export interface Concept { id: number; name: string; is_load_bearing: boolean; }
export interface Topic { id: number; title: string; concepts: Concept[]; }
export interface EventOut { kind: string; detail: string; }
export interface MessageOut { role: 'user' | 'tutor'; content: string; }
export interface Conversation {
  id: number; concept_id: number; attempt_logged: boolean;
  assistance_level: string; challenge_level: string; messages: MessageOut[];
}
export interface SendResult {
  reply: string; attempt_logged: boolean;
  assistance_level: string; challenge_level: string; events: EventOut[];
}
```

- [ ] **Step 2: Create `frontend/src/lib/api.ts`**

```typescript
import type { Conversation, SendResult, Topic } from './types';

async function j<T>(r: Response): Promise<T> {
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json() as Promise<T>;
}

export const api = {
  listTopics: () => fetch('/api/topics').then(j<Topic[]>),
  startConversation: (topic_id: number, concept_id: number) =>
    fetch('/api/conversations', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ topic_id, concept_id })
    }).then(j<Conversation>),
  sendMessage: (id: number, content: string) =>
    fetch(`/api/conversations/${id}/messages`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ content })
    }).then(j<SendResult>)
};
```

- [ ] **Step 3: Write `frontend/src/lib/api.test.ts`**

```typescript
import { describe, expect, it, vi } from 'vitest';
import { api } from './api';

describe('api.sendMessage', () => {
  it('posts content and returns the parsed result', async () => {
    const result = {
      reply: 'Hint: try first', attempt_logged: false,
      assistance_level: 'low', challenge_level: 'high', events: []
    };
    global.fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => result } as Response);

    const out = await api.sendMessage(1, 'answer please');

    expect(global.fetch).toHaveBeenCalledWith('/api/conversations/1/messages', expect.objectContaining({ method: 'POST' }));
    expect(out.reply).toBe('Hint: try first');
  });
});
```

- [ ] **Step 4: Add Vitest and run the test**

```bash
cd frontend && npm install -D vitest
npx vitest run src/lib/api.test.ts
```

Expected: 1 passed

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib frontend/package.json frontend/package-lock.json
git commit -m "feat: frontend api client + types + vitest test"
```

---

## Task 17: Tutor chat page (UI + levels indicator + trace)

**Files:**
- Create/replace: `frontend/src/routes/+page.svelte`

- [ ] **Step 1: Replace `frontend/src/routes/+page.svelte`**

```svelte
<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Conversation, EventOut, MessageOut, Topic } from '$lib/types';

  let topic = $state<Topic | null>(null);
  let conversation = $state<Conversation | null>(null);
  let messages = $state<MessageOut[]>([]);
  let events = $state<EventOut[]>([]);
  let levels = $state({ assistance: '—', challenge: '—', attempt: false });
  let input = $state('');
  let busy = $state(false);

  onMount(async () => {
    const topics = await api.listTopics();
    topic = topics[0] ?? null;
    if (topic && topic.concepts[0]) {
      conversation = await api.startConversation(topic.id, topic.concepts[0].id);
      levels = {
        assistance: conversation.assistance_level,
        challenge: conversation.challenge_level,
        attempt: conversation.attempt_logged
      };
    }
  });

  async function send() {
    if (!conversation || !input.trim() || busy) return;
    const content = input;
    input = '';
    messages = [...messages, { role: 'user', content }];
    busy = true;
    try {
      const r = await api.sendMessage(conversation.id, content);
      messages = [...messages, { role: 'tutor', content: r.reply }];
      events = r.events;
      levels = { assistance: r.assistance_level, challenge: r.challenge_level, attempt: r.attempt_logged };
    } finally {
      busy = false;
    }
  }
</script>

<main class="mx-auto max-w-2xl p-6">
  <header class="mb-4">
    <h1 class="text-2xl font-semibold">{topic?.title ?? 'Adaptive Academy'}</h1>
    <p class="text-sm text-gray-500">
      Concept: {topic?.concepts[0]?.name ?? '—'}
    </p>
    <div class="mt-2 flex gap-2 text-xs">
      <span class="rounded bg-blue-100 px-2 py-1">assistance: {levels.assistance}</span>
      <span class="rounded bg-purple-100 px-2 py-1">challenge: {levels.challenge}</span>
      <span class="rounded px-2 py-1 {levels.attempt ? 'bg-green-100' : 'bg-gray-100'}">
        attempt: {levels.attempt ? 'logged' : 'not yet'}
      </span>
    </div>
  </header>

  <section class="mb-4 flex flex-col gap-3">
    {#each messages as m}
      <div class="rounded-lg px-3 py-2 {m.role === 'user' ? 'self-end bg-gray-100' : 'self-start bg-blue-50'}">
        {m.content}
      </div>
    {/each}
    {#if busy}<div class="self-start text-sm text-gray-400">tutor is thinking…</div>{/if}
  </section>

  <form class="flex gap-2" onsubmit={(e) => { e.preventDefault(); send(); }}>
    <input
      class="flex-1 rounded border px-3 py-2"
      bind:value={input}
      placeholder="Ask the tutor… (it won't just hand you the answer)"
    />
    <button class="rounded bg-blue-600 px-4 py-2 text-white disabled:opacity-50" disabled={busy}>
      Send
    </button>
  </form>

  {#if events.length}
    <details class="mt-6 text-xs text-gray-500">
      <summary>What the agents did ({events.length})</summary>
      <ul class="mt-2 space-y-1">
        {#each events as e}
          <li><code>{e.kind}</code> {e.detail}</li>
        {/each}
      </ul>
    </details>
  {/if}
</main>
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/routes/+page.svelte
git commit -m "feat: tutor chat page with levels indicator + agent trace"
```

---

## Task 18: End-to-end manual verification

**Files:** none (verification only)

- [ ] **Step 1: Reset DB, migrate, seed**

Run: `rm -f adaptive_academy.db && uv run alembic upgrade head && uv run aa seed`
Expected: `Seeded topic 1 with 4 concepts.`

- [ ] **Step 2: Start backend** (terminal 1)

Run: `just api`
Expected: uvicorn serving on :8000; `curl -s localhost:8000/api/health` → `{"status":"ok"}`

- [ ] **Step 3: Start frontend** (terminal 2)

Run: `just frontend`
Expected: SvelteKit on http://localhost:5173

- [ ] **Step 4: Manual generation-first check (requires `ANTHROPIC_API_KEY` in `.env`)**

In the browser at :5173:
1. Confirm the header shows **assistance: low / challenge: high** (expert defaults).
2. Type "just give me the full answer for self-attention." → Expect a **hint or
   question, not a full solution**; "attempt: not yet"; the trace shows
   `tool:reveal_solution:blocked` (if the model attempted a reveal) or simply a hint.
3. Make a real attempt ("I think attention is softmax(QKᵀ/√d)·V because…"). → Expect the
   indicator to flip to **attempt: logged** (trace shows `tool:log_attempt`), after which
   the tutor is willing to confirm/expand.

- [ ] **Step 5: Full automated suite green**

Run: `uv run pytest -q && (cd frontend && npx vitest run)`
Expected: all backend + frontend tests pass.

- [ ] **Step 6: Commit a short run log (optional)**

```bash
git commit --allow-empty -m "chore: walking skeleton verified end-to-end"
```

---

## Done — definition of done recap

At the end of this plan you can run `just api` + `just frontend`, open `:5173`, and hold a
multi-turn, **generation-first** conversation with the Tutor about a seeded concept — with
the **assistance/challenge levels visible**, the **attempt-gate enforced in code**, and an
**observable agent trace** — on the plumbing + orchestration spine that the Researcher,
CurriculumDirector, Assessor, and retention layer plug into in later plans.
