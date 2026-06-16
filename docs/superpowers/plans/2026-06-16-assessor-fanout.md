# Assessor Fan-out — Source-Grounded Anchors + source_quiz Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fan out over accepted SourceDocs to generate source-grounded `ReferenceAnchor`s, then wire the `source_quiz` probe so the Assessor grades against external ground truth — not just a self-generated rubric.

**Architecture:** A new client seam (`AnchorClient` Protocol + `ScriptedAnchorClient` + `AnthropicAnchorClient`) mirroring Plan 2's Researcher fan-out. A new `engine/anchors.py` (pure helpers + a `ThreadPoolExecutor` fan-out orchestrator) generates and persists anchors. `engine/assess.py` gains a `source_quiz` branch grading against a resolved anchor. New `routes_anchors.py` exposes generate/list; `AssessIn` gains `anchor_id`; `ConceptOut` gains computed `has_anchor`. Frontend adds a generate affordance + re-enables source_quiz where an anchor exists. **No migration** (`ReferenceAnchor` + `Assessment.anchor_id` already exist from Plan 4).

**Tech Stack:** Python 3.12 · FastAPI · SQLModel/SQLite · pytest · SvelteKit 2 / Svelte 5 runes / vitest.

**Spec:** `docs/superpowers/specs/2026-06-16-assessor-fanout.md`. Read §2 (locked decisions) before starting.

**Baseline:** branch `redesign/assessor-fanout`, alembic head `58d8eefb9417`, 110 backend + 8 frontend tests green.

**Reference patterns to mirror (read first):** `src/adaptive_academy/engine/research.py` (fan-out orchestrator: `ThreadPoolExecutor` + `as_completed`, per-unit ordered collection, emit/persist/commit/refresh), `src/adaptive_academy/llm/researcher_types.py` (Protocol + dataclasses), `src/adaptive_academy/llm/scripted_researcher.py` (thread-safe by-key double), `src/adaptive_academy/engine/assess.py` (`assess_concept`, `build_grade_prompt` with its `reference` param, `_PROBE_TEXT`), `src/adaptive_academy/models.py` (`ReferenceAnchor`, `SourceDoc`, `Assessment`, `Concept`).

---

## File Structure

- Create: `src/adaptive_academy/llm/anchor_types.py` — `AnchorBrief`, `RawAnchor`, `AnchorClient` Protocol.
- Create: `src/adaptive_academy/llm/scripted_anchor.py` — thread-safe by-source test double.
- Create: `src/adaptive_academy/llm/anthropic_anchor.py` — real client (structured LLM call per source).
- Create: `src/adaptive_academy/engine/anchors.py` — pure helpers + fan-out orchestrator.
- Create: `src/adaptive_academy/api/routes_anchors.py` — generate/list endpoints.
- Modify: `src/adaptive_academy/engine/assess.py` — `source_quiz` branch + `AnchorError` + `anchor_id` param.
- Modify: `src/adaptive_academy/api/schemas.py` — `AnchorOut`, `AnchorGenOut`; `AssessIn.anchor_id`; `ConceptOut.has_anchor`.
- Modify: `src/adaptive_academy/api/routes_assess.py` — pass `anchor_id`, map `AnchorError` → 400.
- Modify: `src/adaptive_academy/api/routes_topics.py` — set `has_anchor` in `ConceptOut` builders.
- Modify: `src/adaptive_academy/api/deps.py` — `get_anchor_client`.
- Modify: `src/adaptive_academy/api/app.py` — register anchors router.
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, assess + review/track pages.
- Create tests: `tests/test_anchors_pure.py`, `tests/test_anchors_parse.py`, `tests/test_scripted_anchor.py`, `tests/test_anchors_orchestrator.py`, `tests/test_assess_source_quiz.py`, `tests/test_api_anchors.py`, `tests/test_integration_source_quiz_loop.py`.

---

## Task 1: Client seam — types, Protocol, scripted double

**Files:**
- Create: `src/adaptive_academy/llm/anchor_types.py`
- Create: `src/adaptive_academy/llm/scripted_anchor.py`
- Test: `tests/test_scripted_anchor.py`

- [ ] **Step 1: Write the failing test** — `tests/test_scripted_anchor.py`:

```python
from adaptive_academy.llm.anchor_types import AnchorBrief, RawAnchor
from adaptive_academy.llm.scripted_anchor import ScriptedAnchorClient


def test_scripted_returns_by_source_and_records_calls():
    anchors = {1: [RawAnchor(question="q1", reference_answer="a1",
                             key_points=["k"], concept_name="softmax")]}
    client = ScriptedAnchorClient(anchors)
    brief = AnchorBrief(source_doc_id=1, title="t", summary="s", url="u",
                        key_concepts=["softmax"])
    out = client.generate(brief)
    assert out[0].question == "q1"
    assert client.calls == [1]
    # Unknown source -> empty.
    assert client.generate(AnchorBrief(source_doc_id=99, title="", summary="",
                                       url="", key_concepts=[])) == []
```

- [ ] **Step 2: Run, expect fail** — `uv run pytest tests/test_scripted_anchor.py -q` → ImportError.

- [ ] **Step 3: Create `anchor_types.py`:**

```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class AnchorBrief:
    """One fan-out unit: generate anchors grounded in a single accepted source."""

    source_doc_id: int
    title: str
    summary: str
    url: str
    key_concepts: list[str] = field(default_factory=list)


@dataclass
class RawAnchor:
    """A candidate anchor returned by a subagent (pre-dedup, pre-persist)."""

    question: str
    reference_answer: str = ""
    key_points: list[str] = field(default_factory=list)
    concept_name: str = ""  # linked to a Concept by name by the orchestrator


class AnchorClient(Protocol):
    """A single fan-out subagent: generates anchors for one source brief."""

    def generate(self, brief: AnchorBrief) -> list[RawAnchor]: ...
```

- [ ] **Step 4: Create `scripted_anchor.py`** (mirror `scripted_researcher.py`):

```python
import threading

from adaptive_academy.llm.anchor_types import AnchorBrief, RawAnchor


class ScriptedAnchorClient:
    """Test double: returns canned RawAnchors keyed by source_doc_id. Thread-safe."""

    def __init__(self, by_source: dict[int, list[RawAnchor]]):
        self._by_source = by_source
        self._lock = threading.Lock()
        self.calls: list[int] = []

    def generate(self, brief: AnchorBrief) -> list[RawAnchor]:
        with self._lock:
            self.calls.append(brief.source_doc_id)
        return list(self._by_source.get(brief.source_doc_id, []))
```

- [ ] **Step 5: Run, expect pass.** Then `uv run pytest -q` (all green) + `uv run ruff check .`.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(anchors): AnchorClient seam + scripted double"`

---

## Task 2: Pure helpers — anchor_key, match_concept, dedupe, parse, brief

**Files:**
- Create: `src/adaptive_academy/engine/anchors.py`
- Test: `tests/test_anchors_pure.py`, `tests/test_anchors_parse.py`

- [ ] **Step 1: Write failing pure tests** — `tests/test_anchors_pure.py`:

```python
from adaptive_academy.engine.anchors import (
    anchor_key,
    dedupe_anchors,
    match_concept,
)
from adaptive_academy.llm.anchor_types import RawAnchor


def test_anchor_key_normalizes():
    assert anchor_key("  Why Does Softmax  Work? ") == anchor_key("why does softmax work?")
    assert anchor_key("a b") != anchor_key("a c")


def test_match_concept_case_insensitive_exact():
    concepts = ["Self-Attention", "softmax"]
    assert match_concept("softmax", concepts) == "softmax"
    assert match_concept("SELF-ATTENTION", concepts) == "Self-Attention"
    assert match_concept("layernorm", concepts) is None


def test_dedupe_anchors_on_source_and_question():
    a = RawAnchor(question="Q?", concept_name="softmax")
    b = RawAnchor(question=" q?  ", concept_name="softmax")  # same key as a
    c = RawAnchor(question="other?", concept_name="softmax")
    # (source_id, anchor) pairs
    out = dedupe_anchors([(1, a), (1, b), (1, c), (2, a)])
    # a/b collapse for source 1; c kept; a re-appears for source 2 (different source)
    assert len(out) == 3
```

- [ ] **Step 2: Write failing parse test** — `tests/test_anchors_parse.py`:

```python
from adaptive_academy.engine.anchors import parse_anchors_json


def test_parse_plain_and_fenced():
    payload = ('{"anchors": [{"question": "q", "reference_answer": "a", '
               '"key_points": ["k1", "k2"], "concept": "softmax"}]}')
    out = parse_anchors_json(payload)
    assert len(out) == 1
    assert out[0].question == "q"
    assert out[0].key_points == ["k1", "k2"]
    assert out[0].concept_name == "softmax"

    fenced = '```json\n{"anchors": []}\n```'
    assert parse_anchors_json(fenced) == []
```

- [ ] **Step 3: Run both, expect fail** — ImportError.

- [ ] **Step 4: Create `engine/anchors.py`** (pure layer only for now):

```python
import json
import re
from dataclasses import dataclass

from adaptive_academy.llm.anchor_types import AnchorBrief, RawAnchor

_WS = re.compile(r"\s+")


def anchor_key(question: str) -> str:
    """Stable dedup signature for an anchor question (lowercased, ws-collapsed, trimmed)."""
    return _WS.sub(" ", question.strip().lower())


def match_concept(name: str, concepts: list[str]) -> str | None:
    """Case-insensitive exact match; returns the canonical concept name or None."""
    target = name.strip().lower()
    for c in concepts:
        if c.strip().lower() == target:
            return c
    return None


def dedupe_anchors(pairs: list[tuple[int, RawAnchor]]) -> list[tuple[int, RawAnchor]]:
    """Collapse duplicates on (source_doc_id, anchor_key(question)); keep first; stable order."""
    seen: set[tuple[int, str]] = set()
    out: list[tuple[int, RawAnchor]] = []
    for source_id, a in pairs:
        if not a.question.strip():
            continue
        key = (source_id, anchor_key(a.question))
        if key in seen:
            continue
        seen.add(key)
        out.append((source_id, a))
    return out


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def parse_anchors_json(text: str) -> list[RawAnchor]:
    data = json.loads(_strip_fences(text))
    out: list[RawAnchor] = []
    for a in (data.get("anchors", []) or []):
        out.append(RawAnchor(
            question=str(a.get("question", "")),
            reference_answer=str(a.get("reference_answer", "")),
            key_points=list(a.get("key_points", []) or []),
            concept_name=str(a.get("concept", a.get("concept_name", "")) or ""),
        ))
    return out


def build_anchor_brief(source, key_concepts: list[str]) -> AnchorBrief:
    """Build a fan-out brief from a SourceDoc row + the topic's key concepts."""
    return AnchorBrief(source_doc_id=source.id, title=source.title,
                       summary=source.summary, url=source.url,
                       key_concepts=list(key_concepts))
```

- [ ] **Step 5: Run both, expect pass.** Full suite + ruff.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(anchors): pure helpers (key, match, dedupe, parse, brief)"`

---

## Task 3: Real client — AnthropicAnchorClient

**Files:**
- Create: `src/adaptive_academy/llm/anthropic_anchor.py`
- Test: `tests/test_anchors_parse.py` (append a client-uses-parse test with a fake LLM)

The real client wraps an `LLMClient` (default `AnthropicLLMClient(role="reasoning")`) and does one structured completion per source, parsing with `parse_anchors_json`. Keep it injectable so it's testable without network.

- [ ] **Step 1: Append failing test** — to `tests/test_anchors_parse.py`:

```python
def test_anthropic_anchor_client_parses_completion():
    from adaptive_academy.llm.anchor_types import AnchorBrief
    from adaptive_academy.llm.anthropic_anchor import AnthropicAnchorClient
    from adaptive_academy.llm.scripted_client import ScriptedLLMClient
    from adaptive_academy.llm.types import LLMResponse

    llm = ScriptedLLMClient([LLMResponse(text='{"anchors": [{"question": "q", '
                            '"reference_answer": "a", "key_points": ["k"], '
                            '"concept": "softmax"}]}')])
    client = AnthropicAnchorClient(llm=llm)
    out = client.generate(AnchorBrief(source_doc_id=1, title="t", summary="s",
                                      url="u", key_concepts=["softmax"]))
    assert out[0].question == "q" and out[0].concept_name == "softmax"
    assert len(llm.calls) == 1
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Create `anthropic_anchor.py`:**

```python
from adaptive_academy.engine.anchors import parse_anchors_json
from adaptive_academy.llm.anchor_types import AnchorBrief, RawAnchor
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.types import LLMClient

_ANCHOR_SYSTEM = (
    "You write grounded quiz anchors for an ADVANCED self-directed learner, from ONE "
    "accepted source. Produce questions whose ANSWERS are checkable against the source's "
    "substance — not trivia. For each, give a concise reference_answer and 3-6 short, "
    "literal key_points (terms/expressions a correct answer must contain), and tag the most "
    "relevant concept from the provided list. Respond with ONLY a JSON object: "
    '{"anchors": [{"question": str, "reference_answer": str, "key_points": [str], '
    '"concept": str}]}. 1-3 anchors. No prose outside the JSON.'
)


def _build_user_msg(brief: AnchorBrief) -> str:
    lines = [f"SOURCE TITLE: {brief.title}", f"URL: {brief.url}",
             f"SOURCE SUMMARY: {brief.summary}",
             f"TOPIC KEY CONCEPTS: {', '.join(brief.key_concepts)}"]
    return "\n".join(lines)


class AnthropicAnchorClient:
    """Generates anchors for one source via a single structured LLM completion."""

    def __init__(self, *, role: str = "reasoning", llm: LLMClient | None = None):
        self._llm = llm if llm is not None else AnthropicLLMClient(role=role)

    def generate(self, brief: AnchorBrief) -> list[RawAnchor]:
        resp = self._llm.complete(
            system=_ANCHOR_SYSTEM,
            messages=[{"role": "user", "content": _build_user_msg(brief)}], tools=[])
        return parse_anchors_json(resp.text)
```

- [ ] **Step 4: Run, expect pass.** Full suite + ruff. (Note: `AnthropicAnchorClient(llm=...)` must NOT construct an `AnthropicLLMClient` when an llm is injected — verify the test passes without `ANTHROPIC_API_KEY`.)

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(anchors): AnthropicAnchorClient (injectable llm)"`

---

## Task 4: Fan-out orchestrator — generate_anchors

**Files:**
- Modify: `src/adaptive_academy/engine/anchors.py`
- Test: `tests/test_anchors_orchestrator.py`

Mirror `research_topic`: emit/plan → fan out with `ThreadPoolExecutor` collecting per-source in source order → link concepts + dedupe → persist `ReferenceAnchor` rows → emit/done → commit/refresh/return.

- [ ] **Step 1: Write failing tests** — `tests/test_anchors_orchestrator.py`:

```python
from adaptive_academy.engine.anchors import AnchorGenError, generate_anchors
from adaptive_academy.llm.anchor_types import RawAnchor
from adaptive_academy.llm.scripted_anchor import ScriptedAnchorClient
from adaptive_academy.models import (
    Concept, ReferenceAnchor, SourceDoc, Topic, TopicFoundation, Track,
)
from sqlmodel import select


def _seed(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["softmax", "self-attention"], prerequisite_map={}))
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    session.add(Concept(track_id=track.id, name="softmax"))
    s1 = SourceDoc(topic_id=topic.id, title="s1", url="u1", status="accepted")
    s2 = SourceDoc(topic_id=topic.id, title="s2", url="u2", status="accepted")
    s3 = SourceDoc(topic_id=topic.id, title="s3", url="u3", status="proposed")  # ignored
    session.add(s1)
    session.add(s2)
    session.add(s3)
    session.commit()
    return topic, track, s1, s2


def test_generate_fans_out_over_accepted_sources(session):
    topic, track, s1, s2 = _seed(session)
    client = ScriptedAnchorClient({
        s1.id: [RawAnchor(question="why softmax?", reference_answer="ra",
                          key_points=["subtract max"], concept_name="softmax")],
        s2.id: [RawAnchor(question="what is attention?", reference_answer="rb",
                          key_points=["QK^T"], concept_name="unmatched")],
    })
    res = generate_anchors(session, topic, anchor_client=client)
    assert len(res.anchors) == 2
    assert sorted(client.calls) == sorted([s1.id, s2.id])  # proposed source skipped
    rows = session.exec(select(ReferenceAnchor)).all()
    by_q = {r.question: r for r in rows}
    assert by_q["why softmax?"].concept_id is not None       # matched "softmax"
    assert by_q["what is attention?"].concept_id is None     # unmatched name
    assert {e.kind for e in res.events} >= {"anchors:plan", "anchors:done"}


def test_generate_is_idempotent(session):
    topic, track, s1, s2 = _seed(session)
    client = ScriptedAnchorClient({
        s1.id: [RawAnchor(question="why softmax?", concept_name="softmax")],
        s2.id: [],
    })
    generate_anchors(session, topic, anchor_client=client)
    res2 = generate_anchors(session, topic, anchor_client=client)
    assert res2.anchors == []  # same (source, question) already exists
    assert len(session.exec(select(ReferenceAnchor)).all()) == 1


def test_generate_raises_without_accepted_sources(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    client = ScriptedAnchorClient({})
    try:
        generate_anchors(session, topic, anchor_client=client)
        assert False, "expected AnchorGenError"
    except AnchorGenError:
        pass
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement** — append to `engine/anchors.py`. Add imports at the TOP with the others: `from concurrent.futures import ThreadPoolExecutor, as_completed`, `from sqlmodel import Session, select`, `from adaptive_academy.llm.anchor_types import AnchorClient` (add to the existing anchor_types import), `from adaptive_academy.models import (AgentEvent, Concept, ReferenceAnchor, SourceDoc, TopicFoundation, Track)`. Then:

```python
class AnchorGenError(Exception):
    """No accepted sources to generate anchors from (route maps to HTTP 400)."""


@dataclass
class AnchorGenResult:
    anchors: list[ReferenceAnchor]
    events: list[AgentEvent]


def _concept_names(session: Session, topic_id: int) -> list[str]:
    rows = session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)).all()
    return [c.name for c in rows]


def _concept_by_name(session: Session, topic_id: int, name: str) -> Concept | None:
    rows = session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)).all()
    for c in rows:
        if c.name.strip().lower() == name.strip().lower():
            return c
    return None


def _existing_keys(session: Session, topic_id: int) -> set[tuple[int, str]]:
    rows = session.exec(
        select(ReferenceAnchor).join(SourceDoc)
        .where(SourceDoc.topic_id == topic_id)).all()
    return {(r.source_doc_id, anchor_key(r.question)) for r in rows}


def generate_anchors(session: Session, topic, *, anchor_client: AnchorClient,
                     max_workers: int = 5) -> AnchorGenResult:
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    sources = session.exec(
        select(SourceDoc).where(SourceDoc.topic_id == topic.id,
                                SourceDoc.status == "accepted")).all()
    sources.sort(key=lambda s: s.rank)
    if not sources:
        raise AnchorGenError("no accepted sources to generate anchors from")

    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)).first()
    key_concepts = foundation.key_concepts if foundation else _concept_names(session, topic.id)

    briefs = [build_anchor_brief(s, key_concepts) for s in sources]
    emit("anchors:plan", f"{len(briefs)} source(s)")

    per_source: list[list[RawAnchor]] = [[] for _ in briefs]
    with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(briefs)))) as ex:
        futures = {ex.submit(anchor_client.generate, b): i for i, b in enumerate(briefs)}
        for fut in as_completed(futures):
            per_source[futures[fut]] = fut.result()

    pairs: list[tuple[int, RawAnchor]] = []
    for i, brief in enumerate(briefs):
        found = per_source[i]
        emit("anchors:subagent", f"source {brief.source_doc_id}: {len(found)} anchor(s)")
        pairs.extend((brief.source_doc_id, a) for a in found)

    existing = _existing_keys(session, topic.id)
    created: list[ReferenceAnchor] = []
    for source_id, a in dedupe_anchors(pairs):
        if (source_id, anchor_key(a.question)) in existing:
            continue
        concept = _concept_by_name(session, topic.id, a.concept_name) if a.concept_name else None
        row = ReferenceAnchor(
            source_doc_id=source_id, concept_id=concept.id if concept else None,
            question=a.question, reference_answer=a.reference_answer,
            key_points=list(a.key_points))
        session.add(row)
        created.append(row)

    emit("anchors:done", f"{len(created)} anchor(s) created")
    session.commit()
    for r in created:
        session.refresh(r)
    return AnchorGenResult(anchors=created, events=events)
```

- [ ] **Step 4: Run, expect pass** (all 3). Full suite + ruff.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(anchors): fan-out orchestrator (generate_anchors)"`

---

## Task 5: Wire source_quiz grading in assess.py

**Files:**
- Modify: `src/adaptive_academy/engine/assess.py`
- Test: `tests/test_assess_source_quiz.py`

Add a `source_quiz` branch that grades against a resolved `ReferenceAnchor`. Add an `anchor_id` param to `assess_concept` and raise `AnchorError` (new) when no anchor can be resolved.

- [ ] **Step 1: Write failing tests** — `tests/test_assess_source_quiz.py`:

```python
import json

from adaptive_academy.engine.assess import AnchorError, assess_concept
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Concept, KnowledgeEstimate, ReferenceAnchor, SourceDoc, Topic, Track,
)


def _seed(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
    src = SourceDoc(topic_id=topic.id, title="s", url="u", status="accepted")
    session.add(src)
    session.commit()
    anchor = ReferenceAnchor(source_doc_id=src.id, concept_id=concept.id,
                             question="Why subtract the max in softmax?",
                             reference_answer="for numerical stability",
                             key_points=["numerical stability", "overflow"])
    session.add(anchor)
    session.commit()
    return topic, concept, anchor


def test_source_quiz_grades_against_anchor(session):
    topic, concept, anchor = _seed(session)
    # LLM grades; the anchor (not a rubric) supplies the gradeable points.
    grade = json.dumps({"score": 0.9, "verdict": "good", "gaps": []})
    llm = ScriptedLLMClient([LLMResponse(text=grade)])
    res = assess_concept(session, concept, "source_quiz",
                         "it avoids overflow for numerical stability", llm=llm)
    assert res.assessment.anchor_id == anchor.id
    assert res.assessment.rubric_id is None
    assert res.assessment.prompt == anchor.question
    assert len(llm.calls) == 1  # NO rubric call — only the grade call


def test_source_quiz_rules_layer_penalizes_omitted_key_point(session):
    topic, concept, anchor = _seed(session)
    grade = json.dumps({"score": 0.9, "verdict": "confident", "gaps": []})
    llm = ScriptedLLMClient([LLMResponse(text=grade)])
    # Response omits BOTH key_points -> deterministic penalty drags the 0.9 down.
    res = assess_concept(session, concept, "source_quiz", "it just works", llm=llm)
    assert res.assessment.score < 0.9
    assert any("omitted required element" in g for g in res.assessment.gaps)


def test_source_quiz_without_anchor_raises(session):
    topic, concept, anchor = _seed(session)
    session.delete(anchor)
    session.commit()
    llm = ScriptedLLMClient([])  # must raise before any LLM call
    try:
        assess_concept(session, concept, "source_quiz", "x", llm=llm)
        assert False, "expected AnchorError"
    except AnchorError:
        pass
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement in `assess.py`.** Add near the top (after imports): import `ReferenceAnchor` into the existing models import, and define:

```python
class AnchorError(Exception):
    """No ReferenceAnchor available for a source_quiz probe (route maps to HTTP 400)."""
```

Add a resolver helper (near `_deliverable_criteria`):

```python
def _resolve_anchor(session: Session, concept: Concept,
                    anchor_id: int | None) -> "ReferenceAnchor":
    if anchor_id is not None:
        anchor = session.get(ReferenceAnchor, anchor_id)
    else:
        anchor = session.exec(
            select(ReferenceAnchor).where(ReferenceAnchor.concept_id == concept.id)
            .order_by(ReferenceAnchor.id)).first()
    if anchor is None:
        raise AnchorError("no anchor for this concept; generate anchors first")
    return anchor
```

Add `anchor_id: int | None = None` to the `assess_concept` signature (keyword-only, alongside the others). Then in the anchor-resolution block, ADD a `source_quiz` branch BEFORE the existing `else` (rubric) branch. The current structure is:

```python
    if kind == "artifact_review":
        criteria = _deliverable_criteria(session, item_id)
        probe = _PROBE_TEXT[kind].format(concept=concept.name)
    else:
        rubric = ensure_rubric(session, concept, llm=llm)
        ...
```

Change to:

```python
    anchor_ref_id: int | None = None
    if kind == "artifact_review":
        criteria = _deliverable_criteria(session, item_id)
        probe = _PROBE_TEXT[kind].format(concept=concept.name)
    elif kind == "source_quiz":
        anchor = _resolve_anchor(session, concept, anchor_id)
        anchor_ref_id = anchor.id
        criteria = anchor.key_points
        must_include = anchor.key_points
        reference = anchor.reference_answer
        probe = anchor.question
    else:
        rubric = ensure_rubric(session, concept, llm=llm)
        rubric_id = rubric.id
        criteria, must_include, weak_signs = rubric.criteria, rubric.must_include, rubric.weak_signs
        probe = _PROBE_TEXT.get(kind, _PROBE_TEXT["self_explanation"]).format(
            concept=concept.name, question=concept.name)
```

Then where the `Assessment(...)` is constructed, set `anchor_id=anchor_ref_id` (the field already exists on the model; it is currently never set). Leave `rubric_id` as-is (None for source_quiz since the rubric branch didn't run).

IMPORTANT: confirm `reference` is already initialized to `""` before the branches (it is) so the `source_quiz` assignment is the only place it becomes non-empty, and `build_grade_prompt` receives it. Also confirm `must_include`/`weak_signs` are initialized before the branches (they are: `must_include: list[str] = []`, `weak_signs: list[str] = []`).

- [ ] **Step 4: Run, expect pass.** Full suite + ruff. Re-run `tests/test_assess_orchestrator.py` and `tests/test_integration_assess_loop.py` to confirm the rubric path is unchanged.

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(assess): source_quiz grades against a ReferenceAnchor"`

---

## Task 6: API — anchors routes, schemas, deps, has_anchor

**Files:**
- Modify: `src/adaptive_academy/api/schemas.py`, `routes_assess.py`, `routes_topics.py`, `deps.py`, `app.py`
- Create: `src/adaptive_academy/api/routes_anchors.py`
- Test: `tests/test_api_anchors.py`

- [ ] **Step 1: Write failing API tests** — `tests/test_api_anchors.py`:

```python
import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_anchor_client, get_llm, get_session
from adaptive_academy.llm.anchor_types import RawAnchor
from adaptive_academy.llm.scripted_anchor import ScriptedAnchorClient
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Concept, KnowledgeEstimate, SourceDoc, Topic, TopicFoundation, Track,
)


def _seed(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["softmax"], prerequisite_map={}))
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
    src = SourceDoc(topic_id=topic.id, title="s", url="u", status="accepted")
    session.add(src)
    session.commit()
    return topic.id, concept.id, src.id


def test_generate_list_and_has_anchor(session):
    app.dependency_overrides[get_session] = lambda: session
    topic_id, cid, sid = _seed(session)
    app.dependency_overrides[get_anchor_client] = lambda: ScriptedAnchorClient({
        sid: [RawAnchor(question="why softmax?", reference_answer="ra",
                        key_points=["numerical stability"], concept_name="softmax")]})
    client = TestClient(app)

    gen = client.post(f"/api/topics/{topic_id}/anchors")
    assert gen.status_code == 200 and len(gen.json()["anchors"]) == 1

    lst = client.get(f"/api/concepts/{cid}/anchors")
    assert lst.status_code == 200 and len(lst.json()) == 1

    topic = client.get(f"/api/topics/{topic_id}").json()
    sm = [c for c in topic["concepts"] if c["id"] == cid][0]
    assert sm["has_anchor"] is True

    # source_quiz now grades against the anchor.
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps({"score": 0.8, "verdict": "ok", "gaps": []}))])
    a = client.post(f"/api/concepts/{cid}/assess",
                    json={"kind": "source_quiz", "response": "numerical stability matters"})
    assert a.status_code == 200
    app.dependency_overrides.clear()


def test_generate_400_without_sources(session):
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    app.dependency_overrides[get_anchor_client] = lambda: ScriptedAnchorClient({})
    client = TestClient(app)
    assert client.post(f"/api/topics/{topic.id}/anchors").status_code == 400
    app.dependency_overrides.clear()


def test_source_quiz_400_without_anchor(session):
    app.dependency_overrides[get_session] = lambda: session
    topic_id, cid, sid = _seed(session)
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([])
    client = TestClient(app)
    r = client.post(f"/api/concepts/{cid}/assess",
                    json={"kind": "source_quiz", "response": "x"})
    assert r.status_code == 400
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: deps** — in `api/deps.py`, add:

```python
from adaptive_academy.llm.anchor_types import AnchorClient
from adaptive_academy.llm.anthropic_anchor import AnthropicAnchorClient


def get_anchor_client() -> AnchorClient:
    return AnthropicAnchorClient(role="reasoning")
```

- [ ] **Step 4: schemas** — in `schemas.py`: add `has_anchor: bool = False` to `ConceptOut`; add `anchor_id: Optional[int] = None` to `AssessIn`; add:

```python
class AnchorOut(BaseModel):
    id: int
    source_doc_id: int
    concept_id: Optional[int] = None
    question: str
    reference_answer: str
    key_points: list[str]


class AnchorGenOut(BaseModel):
    anchors: list[AnchorOut]
    events: list[EventOut]
```

- [ ] **Step 5: routes_anchors.py** — create:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_anchor_client, get_session
from adaptive_academy.api.schemas import AnchorGenOut, AnchorOut, EventOut
from adaptive_academy.engine.anchors import AnchorGenError, generate_anchors
from adaptive_academy.llm.anchor_types import AnchorClient
from adaptive_academy.models import Concept, ReferenceAnchor, SourceDoc, Topic

topic_router = APIRouter(prefix="/api/topics", tags=["anchors"])
concept_router = APIRouter(prefix="/api/concepts", tags=["anchors"])


def _anchor_out(a: ReferenceAnchor) -> AnchorOut:
    return AnchorOut(id=a.id, source_doc_id=a.source_doc_id, concept_id=a.concept_id,
                     question=a.question, reference_answer=a.reference_answer,
                     key_points=a.key_points)


@topic_router.post("/{topic_id}/anchors", response_model=AnchorGenOut)
def generate(topic_id: int, session: Session = Depends(get_session),
             anchor_client: AnchorClient = Depends(get_anchor_client)) -> AnchorGenOut:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(404, "topic not found")
    try:
        result = generate_anchors(session, topic, anchor_client=anchor_client)
    except AnchorGenError as e:
        raise HTTPException(400, str(e))
    return AnchorGenOut(anchors=[_anchor_out(a) for a in result.anchors],
                        events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events])


@topic_router.get("/{topic_id}/anchors", response_model=list[AnchorOut])
def list_topic_anchors(topic_id: int, concept_id: int | None = None,
                       session: Session = Depends(get_session)) -> list[AnchorOut]:
    q = (select(ReferenceAnchor).join(SourceDoc)
         .where(SourceDoc.topic_id == topic_id))
    if concept_id is not None:
        q = q.where(ReferenceAnchor.concept_id == concept_id)
    return [_anchor_out(a) for a in session.exec(q).all()]


@concept_router.get("/{concept_id}/anchors", response_model=list[AnchorOut])
def list_concept_anchors(concept_id: int,
                         session: Session = Depends(get_session)) -> list[AnchorOut]:
    rows = session.exec(
        select(ReferenceAnchor).where(ReferenceAnchor.concept_id == concept_id)).all()
    return [_anchor_out(a) for a in rows]
```

- [ ] **Step 6: register** — in `app.py`, import and include both routers:

```python
from adaptive_academy.api.routes_anchors import (
    concept_router as anchor_concept_router,
    topic_router as anchor_topic_router,
)
```
```python
    app.include_router(anchor_topic_router)
    app.include_router(anchor_concept_router)
```

- [ ] **Step 7: has_anchor** — in `routes_topics.py`, in `_topic_out`'s `ConceptOut(...)` construction, add `has_anchor=` computed via a helper. Add near the top of the file:

```python
from adaptive_academy.models import ReferenceAnchor
```
and a helper:
```python
def _has_anchor(session: Session, concept_id: int) -> bool:
    return session.exec(
        select(ReferenceAnchor).where(ReferenceAnchor.concept_id == concept_id)).first() is not None
```
Then pass `has_anchor=_has_anchor(session, c.id)` in the `ConceptOut(...)` inside `_topic_out`. (The `_curriculum_out` ConceptOut builder may keep the default `False` — the topic view is what drives the assess UI; note this in the commit if you leave it.)

- [ ] **Step 8: routes_assess** — pass `anchor_id` and map `AnchorError` → 400. Change the `assess` route:

```python
from adaptive_academy.engine.assess import AnchorError, assess_concept, ensure_rubric
```
```python
    try:
        result = assess_concept(session, concept, body.kind, body.response, llm=llm,
                                confidence_predicted=body.confidence_predicted,
                                baseline_id=body.baseline_id, item_id=body.item_id,
                                anchor_id=body.anchor_id)
    except AnchorError as e:
        raise HTTPException(400, str(e))
```

- [ ] **Step 9: Run, expect pass** (`tests/test_api_anchors.py`), then full suite + ruff. Verify existing assess/topic tests still pass with the new `has_anchor` field (it has a default).

- [ ] **Step 10: Commit** — `git add -A && git commit -m "feat(anchors): generate/list routes, has_anchor, source_quiz anchor_id"`

---

## Task 7: Integration loop + frontend

**Files:**
- Test: `tests/test_integration_source_quiz_loop.py`
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, assess page, review or track page
- Test: a vitest spec mirroring `frontend/src/lib/api.test.ts`

- [ ] **Step 1: Integration test** — `tests/test_integration_source_quiz_loop.py` (mirror `test_integration_remediate_loop.py`): seed topic+foundation+track+concept+accepted source; generate anchors via the API with a `ScriptedAnchorClient`; then run a `source_quiz` assessment against the anchor with a scripted grade; assert `Assessment.anchor_id` is set and the `KnowledgeEstimate` updated. Use `app.dependency_overrides` for `get_session`, `get_anchor_client`, `get_llm` (see `tests/test_api_anchors.py` for the exact override pattern).

```python
import json

from fastapi.testclient import TestClient
from sqlmodel import select

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_anchor_client, get_llm, get_session
from adaptive_academy.llm.anchor_types import RawAnchor
from adaptive_academy.llm.scripted_anchor import ScriptedAnchorClient
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, KnowledgeEstimate, SourceDoc, Topic, TopicFoundation, Track,
)


def test_generate_anchor_then_source_quiz_updates_estimate(session):
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="Build LLMs")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["softmax"], prerequisite_map={}))
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
    src = SourceDoc(topic_id=topic.id, title="s", url="u", status="accepted")
    session.add(src)
    session.commit()
    client = TestClient(app)

    app.dependency_overrides[get_anchor_client] = lambda: ScriptedAnchorClient({
        src.id: [RawAnchor(question="Why subtract the max?", reference_answer="stability",
                           key_points=["numerical stability"], concept_name="softmax")]})
    gen = client.post(f"/api/topics/{topic.id}/anchors")
    assert gen.status_code == 200 and len(gen.json()["anchors"]) == 1

    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps({"score": 0.2, "verdict": "weak", "gaps": []}))])
    a = client.post(f"/api/concepts/{concept.id}/assess",
                    json={"kind": "source_quiz", "response": "no idea"})
    assert a.status_code == 200 and a.json()["estimate_level"] == "low"

    rows = session.exec(select(Assessment)).all()
    assert rows[-1].anchor_id is not None
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run, expect pass.** Full backend suite + ruff.

- [ ] **Step 3: Frontend types/api** — in `types.ts`: add `has_anchor?: boolean;` to `Concept`; add `anchor_id?: number | null;` to `AssessBody`; add:

```typescript
export interface Anchor { id: number; source_doc_id: number; concept_id: number | null; question: string; reference_answer: string; key_points: string[]; }
export interface AnchorGen { anchors: Anchor[]; events: EventOut[]; }
```
In `api.ts`: add `Anchor, AnchorGen` to the type import; add:
```typescript
  generateAnchors: (topicId: number) =>
    fetch(`/api/topics/${topicId}/anchors`, { method: 'POST' }).then(j<AnchorGen>),
  listConceptAnchors: (conceptId: number) =>
    fetch(`/api/concepts/${conceptId}/anchors`).then(j<Anchor[]>),
```

- [ ] **Step 4: Assess page** — in `assess/+page.svelte`: when the selected concept `has_anchor`, include a **Source quiz** `<option value="source_quiz">` in the Probe `<select>` (currently only self_explanation/calibration/artifact_review). When `kind === 'source_quiz'`, fetch the concept's anchors on concept change and show the first anchor's `question` above the textarea as the prompt; pass no `anchor_id` (engine picks the lowest-id). Keep it minimal — a `let anchorQuestion = $state<string|null>(null)` populated from `api.listConceptAnchors(conceptId)` when kind is source_quiz. Guard: only show the option if the chosen concept has `has_anchor` (look it up from `cur.concepts`, which now carries `has_anchor`). NOTE: `getCurriculum`'s ConceptOut may not include `has_anchor` if Task 6 left `_curriculum_out` at default — if so, fetch the topic (`/api/topics/{id}`) for the `has_anchor` flags, or update `_curriculum_out` to populate it. Pick the smaller change and keep it consistent.

- [ ] **Step 5: Generate affordance** — on the review page (`review/+page.svelte`) or track page, add a "Generate quizzes from sources" button calling `api.generateAnchors(topicId)` and reporting the count. Choose whichever page already shows sources/curriculum actions; keep styling consistent.

- [ ] **Step 6: vitest** — mirror `frontend/src/lib/api.test.ts`: assert `api.generateAnchors` POSTs to `/api/topics/{id}/anchors` and `api.listConceptAnchors` GETs `/api/concepts/{id}/anchors`, consistent with the existing fetch-mock style.

- [ ] **Step 7: Frontend tests** — from `frontend/`: `npm test`, all green.

- [ ] **Step 8: Commit** — `git add -A && git commit -m "feat(anchors): integration loop + source_quiz UI + generate affordance"`

---

## Task 8: Final verification

- [ ] **Step 1:** `uv run pytest -q` — 110 prior + new tests, all green.
- [ ] **Step 2:** `uv run ruff check .` — clean.
- [ ] **Step 3:** `uv run alembic upgrade head` then `uv run alembic downgrade -1 && uv run alembic upgrade head` — clean (no NEW migration this milestone; head stays `58d8eefb9417`).
- [ ] **Step 4:** `just seed` still works.
- [ ] **Step 5:** Frontend tests green.
- [ ] **Step 6:** Dispatch the final adversarial code reviewer over the whole branch diff, then proceed to `superpowers:finishing-a-development-branch` (merge to main + push — the user's standing preference).

---

## Self-Review (author)

- **Spec coverage:** fan-out generation (Tasks 1–4) ✓; Protocol seam + thread-safe by-source double (Task 1) ✓; idempotent dedup (Tasks 2,4) ✓; concept linking by name (Tasks 2,4) ✓; source_quiz grades against anchor + 400 (Task 5) ✓; anti-sycophancy via key_points→must_include (Task 5) ✓; endpoints + has_anchor (Task 6) ✓; navigation/UI (Task 7) ✓; integration loop (Task 7) ✓; no migration (Task 8) ✓.
- **Type consistency:** `RawAnchor(question, reference_answer, key_points, concept_name)` and `AnchorBrief(source_doc_id, title, summary, url, key_concepts)` used identically across Tasks 1–4; `generate_anchors(session, topic, *, anchor_client, max_workers=5)` stable across Tasks 4 & 6; `assess_concept(..., anchor_id=None)` added in Task 5 and called in Task 6/8; `ReferenceAnchor` fields (source_doc_id, concept_id, question, reference_answer, key_points) match the model in `models.py`.
- **Determinism under concurrency:** the scripted double is keyed by `source_doc_id` (not a shared queue) and is lock-guarded, so parallel fan-out tests are deterministic — the exact reason Plan 2 keyed its researcher double by angle.
- **No-rubric-call invariant:** `source_quiz` must NOT call `ensure_rubric` (Task 5 test asserts a single LLM call). Confirmed: the new branch sits before the `else` rubric branch and supplies criteria/must_include/reference from the anchor.
- **Placeholder scan:** none — every code step is concrete; the one judgment call (where `has_anchor` is read in the assess UI) is spelled out with both acceptable resolutions in Task 7 Step 4.
```
