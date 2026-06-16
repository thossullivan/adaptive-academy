# CurriculumDirector Adapt-Mode (Remediation) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When the Assessor flags a gap, the CurriculumDirector injects targeted, non-destructive, idempotent remediation Items into the existing Track — closing the adaptive loop end-to-end.

**Architecture:** A new pure+orchestrator engine module `engine/remediate.py` (parallels `curriculum.py`/`assess.py`): load latest Assessment + KnowledgeEstimate → one structured LLM call → deterministic per-gap idempotency filter + phase placement → append `Item`s marked `added_by="remediation"` → emit topic-scoped `AgentEvent`s. A new `routes_remediate.py` exposes `POST /api/concepts/{id}/remediate`. `Item` gains two additive columns (`added_by`, `remediation_key`); `ItemOut` gains derived `is_remediation`. Frontend flags remediation items and adds a "Remediate" affordance after a weak assessment.

**Tech Stack:** Python 3.12 · FastAPI · SQLModel/SQLite · Alembic · pytest · SvelteKit 2 / Svelte 5 runes / vitest.

**Spec:** `docs/superpowers/specs/2026-06-16-adapt-mode.md`. Read §2 (locked decisions) before starting.

**Baseline:** branch `redesign/adapt-mode`, alembic head `8b27f2ac6c62`, 87 backend + 7 frontend tests green.

---

## File Structure

- Create: `src/adaptive_academy/engine/remediate.py` — pure helpers + orchestrator.
- Create: `src/adaptive_academy/api/routes_remediate.py` — the endpoint.
- Create: `alembic/versions/<rev>_item_remediation_columns.py` — additive migration.
- Create tests: `tests/test_remediate_pure.py`, `tests/test_remediate_parse.py`, `tests/test_remediate_prompt.py`, `tests/test_remediate_orchestrator.py`, `tests/test_api_remediate.py`, `tests/test_integration_remediate_loop.py`.
- Modify: `src/adaptive_academy/models.py` (Item: add `added_by`, `remediation_key`).
- Modify: `src/adaptive_academy/api/schemas.py` (ItemOut: add `is_remediation`; add `RemediateIn`, `RemediationOut`).
- Modify: `src/adaptive_academy/api/routes_topics.py` (`_curriculum_out` sets `is_remediation`).
- Modify: `src/adaptive_academy/api/routes_items.py` (`patch_item` sets `is_remediation`).
- Modify: `src/adaptive_academy/api/app.py` (register remediate router).
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/routes/topics/[id]/track/+page.svelte`, `frontend/src/routes/topics/[id]/assess/+page.svelte`.

---

## Task 1: Add remediation columns to Item + migration

**Files:**
- Modify: `src/adaptive_academy/models.py` (class `Item`, after `concept_refs`)
- Create: `alembic/versions/<rev>_item_remediation_columns.py`
- Test: `tests/test_remediate_pure.py` (model defaults sub-test here; pure helpers in Task 2)

- [ ] **Step 1: Write the failing test** — `tests/test_remediate_pure.py`:

```python
from adaptive_academy.models import Item


def test_item_remediation_defaults():
    it = Item(phase_id=1, text="x")
    assert it.added_by == "curriculum"
    assert it.remediation_key == ""
```

- [ ] **Step 2: Run it, expect fail** — `uv run pytest tests/test_remediate_pure.py -q` → AttributeError on `added_by`.

- [ ] **Step 3: Add the columns** — in `models.py`, class `Item`, immediately after the `concept_refs` line, add:

```python
    added_by: str = "curriculum"  # "curriculum" | "remediation"
    remediation_key: str = ""  # idempotency signature for remediation items
```

- [ ] **Step 4: Run it, expect pass.**

- [ ] **Step 5: Create the migration.** First get a revision id: `uv run python -c "import uuid; print(uuid.uuid4().hex[:12])"`. Create `alembic/versions/<rev>_item_remediation_columns.py` (replace `<rev>` with that value):

```python
"""item remediation columns

Revision ID: <rev>
Revises: 8b27f2ac6c62
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "<rev>"
down_revision = "8b27f2ac6c62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Native ADD COLUMN (SQLite) — additive, no table recreation. server_default
    # backfills existing rows; column default in the model handles new ORM rows.
    op.add_column("item", sa.Column("added_by", sa.String(), nullable=False,
                                    server_default="curriculum"))
    op.add_column("item", sa.Column("remediation_key", sa.String(), nullable=False,
                                    server_default=""))


def downgrade() -> None:
    op.drop_column("item", "remediation_key")
    op.drop_column("item", "added_by")
```

- [ ] **Step 6: Verify migration round-trips.**

Run: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: no errors; `uv run alembic heads` shows the new `<rev>` as head.

- [ ] **Step 7: Verify round-trips after seed** (FK-safe with data present):

Run: `just seed && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: no errors. (If `just seed` is unavailable, run the project's seed entrypoint; check `justfile`.)

- [ ] **Step 8: Commit** — `git add -A && git commit -m "feat(remediate): add added_by/remediation_key columns to Item"`

---

## Task 2: Pure helpers — gap_key, plan_remediation_items, choose_target_phase

**Files:**
- Create: `src/adaptive_academy/engine/remediate.py`
- Test: `tests/test_remediate_pure.py` (append)

These are pure functions over plain data — no DB, no LLM. The orchestrator (Task 4) calls them.

- [ ] **Step 1: Write failing tests** — append to `tests/test_remediate_pure.py`:

```python
from dataclasses import dataclass

from adaptive_academy.engine.remediate import (
    PlacedItem,
    choose_target_phase,
    gap_key,
    plan_remediation_items,
)


def test_gap_key_normalizes():
    assert gap_key("  Omitted required element: Softmax  ") == gap_key(
        "omitted required element: softmax")
    assert gap_key("a   b") == gap_key("a b")
    assert gap_key("X") != gap_key("Y")


def test_plan_skips_already_covered_gaps():
    gaps = ["gap one", "gap two"]
    covered = {gap_key("gap one")}
    proposed = [{"type": "build", "text": "do A"}, {"type": "write", "text": "do B"}]
    items = plan_remediation_items(proposed, "softmax", gaps, covered)
    # Only the uncovered gap ("gap two") yields an item.
    assert len(items) == 1
    assert items[0].remediation_key == gap_key("gap two")
    assert items[0].concept_refs == ["softmax"]
    assert items[0].added_by == "remediation"


def test_plan_is_idempotent_when_all_covered():
    gaps = ["gap one"]
    covered = {gap_key("gap one")}
    assert plan_remediation_items([{"type": "build", "text": "x"}], "c", gaps, covered) == []


def test_plan_falls_back_when_fewer_items_than_gaps():
    gaps = ["alpha", "beta"]
    items = plan_remediation_items([{"type": "build", "text": "only one"}], "c", gaps, set())
    assert len(items) == 2  # one per uncovered gap; deterministic fallback for the 2nd
    assert all(i.text for i in items)  # no empty text
    assert items[0].text == "only one"


def test_plan_maps_item_types_and_defaults_to_build():
    items = plan_remediation_items([{"text": "no type"}], "c", ["g"], set())
    assert items[0].type == "build"  # default when type missing/invalid


# choose_target_phase: (position, [item statuses]) -> chosen index
def _phase(statuses):
    @dataclass
    class _P:
        statuses: list

    return _P(statuses)


def test_choose_target_phase_picks_earliest_unfinished():
    phases = [_phase(["done", "done"]), _phase(["done", "todo"]), _phase(["todo"])]
    assert choose_target_phase([p.statuses for p in phases]) == 1


def test_choose_target_phase_falls_back_to_last_when_all_done():
    phases = [_phase(["done"]), _phase(["done"])]
    assert choose_target_phase([p.statuses for p in phases]) == 1


def test_choose_target_phase_empty_phase_counts_as_unfinished():
    assert choose_target_phase([["done"], []]) == 1
    assert choose_target_phase([[]]) == 0
```

- [ ] **Step 2: Run, expect fail** — `uv run pytest tests/test_remediate_pure.py -q` → ImportError.

- [ ] **Step 3: Implement the pure layer** — create `src/adaptive_academy/engine/remediate.py`:

```python
import json
import re
from dataclasses import dataclass, field

_VALID_TYPES = {"read", "build", "write", "watch"}
_WS = re.compile(r"\s+")


def gap_key(gap: str) -> str:
    """Stable idempotency signature for a gap string (lowercased, ws-collapsed, trimmed)."""
    return _WS.sub(" ", gap.strip().lower())


@dataclass
class PlacedItem:
    text: str
    type: str
    concept_refs: list[str]
    remediation_key: str
    added_by: str = "remediation"


def _item_type(raw) -> str:
    t = str(raw or "").strip().lower()
    return t if t in _VALID_TYPES else "build"


def plan_remediation_items(
    proposed: list[dict], concept_name: str, gaps: list[str], covered: set[str],
) -> list[PlacedItem]:
    """One remediation item per *uncovered* gap (idempotent), in gap order.

    `proposed` is the LLM's item list; item i is matched to uncovered gap i. When the
    LLM returns fewer items than uncovered gaps, fall back to a deterministic template
    so every uncovered gap is addressed and no item has empty text.
    """
    out: list[PlacedItem] = []
    uncovered = [g for g in gaps if gap_key(g) not in covered]
    for i, gap in enumerate(uncovered):
        src = proposed[i] if i < len(proposed) else {}
        text = str(src.get("text") or "").strip() or f"Remediate: {gap} (re: {concept_name})"
        out.append(PlacedItem(text=text, type=_item_type(src.get("type")),
                              concept_refs=[concept_name], remediation_key=gap_key(gap)))
    return out


def choose_target_phase(phase_item_statuses: list[list[str]]) -> int:
    """Index of the 'current' phase: earliest with a non-`done` item (or no items);
    else the last phase. Empty input is invalid (caller guarantees >=1 phase)."""
    for i, statuses in enumerate(phase_item_statuses):
        if not statuses or any(s != "done" for s in statuses):
            return i
    return len(phase_item_statuses) - 1
```

- [ ] **Step 4: Run, expect pass.**

- [ ] **Step 5: Commit** — `git add -A && git commit -m "feat(remediate): pure helpers (gap_key, plan, placement)"`

---

## Task 3: Parsing + prompt builder

**Files:**
- Modify: `src/adaptive_academy/engine/remediate.py`
- Test: `tests/test_remediate_parse.py`, `tests/test_remediate_prompt.py`

- [ ] **Step 1: Write failing parse tests** — `tests/test_remediate_parse.py`:

```python
from adaptive_academy.engine.remediate import parse_remediation_json


def test_parse_plain_json():
    d = parse_remediation_json(
        '{"items": [{"type": "build", "text": "t"}], "revisit": {"text": "r"}}')
    assert d.items == [{"type": "build", "text": "t"}]
    assert d.revisit == {"text": "r"}


def test_parse_strips_fences_and_handles_missing():
    d = parse_remediation_json('```json\n{"items": []}\n```')
    assert d.items == []
    assert d.revisit is None
```

- [ ] **Step 2: Write failing prompt tests** — `tests/test_remediate_prompt.py`:

```python
from adaptive_academy.engine.remediate import build_remediate_prompt


def test_prompt_includes_gaps_level_and_evidence_framing():
    system, user = build_remediate_prompt(
        "softmax", ["omitted: subtract the max"], "low",
        foundation_overview="ov", sources_summary="s1")
    assert "softmax" in user
    assert "omitted: subtract the max" in user
    assert "low" in user.lower()
    # Evidence rules live in the system prompt.
    assert "low-assistance" in system.lower() or "expertise-reversal" in system.lower()
    assert "project" in system.lower() or "problem-first" in system.lower()
    assert "json" in system.lower()
```

- [ ] **Step 3: Run both, expect fail** — ImportError.

- [ ] **Step 4: Implement** — append to `engine/remediate.py`:

```python
@dataclass
class RemediationDraft:
    items: list[dict] = field(default_factory=list)
    revisit: dict | None = None


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def parse_remediation_json(text: str) -> RemediationDraft:
    d = json.loads(_strip_fences(text))
    revisit = d.get("revisit") or None
    return RemediationDraft(
        items=list(d.get("items", []) or []),
        revisit=revisit if isinstance(revisit, dict) else None,
    )


_REMEDIATE_SYSTEM = (
    "You are a CurriculumDirector in ADAPT MODE for an ADVANCED, self-directed adult "
    "learner who just revealed specific GAPS on one concept. Propose a SHORT, targeted "
    "remediation. Evidence-driven rules (follow them):\n"
    "- Default to LOW-ASSISTANCE, PROJECT/PROBLEM-FIRST items (expertise-reversal effect: "
    "high guidance harms experts). Each item must directly attack a NAMED gap.\n"
    "- Key the remediation to the learner's PRIOR-KNOWLEDGE level, not raw difficulty.\n"
    "- Deliberate-practice drills are SUPPORTING, never the spine.\n"
    "- Propose ONE item per listed gap, plus optionally ONE spaced 'revisit' for later.\n"
    'Respond with ONLY a JSON object: {"items": [{"type": "read"|"build"|"write", '
    '"text": str}], "revisit": {"text": str} | null}. No prose outside the JSON.'
)


def build_remediate_prompt(
    concept_name: str, gaps: list[str], level: str, *,
    foundation_overview: str = "", sources_summary: str = "",
) -> tuple[str, str]:
    lines = [
        f"CONCEPT: {concept_name}",
        f"LEARNER PRIOR-KNOWLEDGE LEVEL: {level}",
        "ASSESSED GAPS (one targeted item each):",
    ]
    lines += [f"- {g}" for g in gaps]
    if foundation_overview:
        lines += ["", f"FOUNDATION OVERVIEW: {foundation_overview}"]
    if sources_summary:
        lines += [f"SOURCES: {sources_summary}"]
    return _REMEDIATE_SYSTEM, "\n".join(lines)
```

- [ ] **Step 5: Run both, expect pass.**

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(remediate): JSON parse + evidence-keyed prompt"`

---

## Task 4: Orchestrator — remediate_concept

**Files:**
- Modify: `src/adaptive_academy/engine/remediate.py`
- Test: `tests/test_remediate_orchestrator.py`

The orchestrator persists items and emits events. It mirrors `assess_concept`'s shape:
resolve context → single LLM call → persist → emit topic-scoped events → commit → return.

- [ ] **Step 1: Write failing tests** — `tests/test_remediate_orchestrator.py`:

```python
import json

from adaptive_academy.engine.remediate import RemediationError, remediate_concept
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, Item, KnowledgeEstimate, Phase, Topic, Track,
)


def _seed(session, gaps):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax", is_load_bearing=True)
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="low", confidence=0.3))
    # Two phases so a revisit can land in a later one.
    p0 = Phase(track_id=track.id, title="P0", position=0)
    p1 = Phase(track_id=track.id, title="P1", position=1)
    session.add(p0)
    session.add(p1)
    session.commit()
    session.add(Item(phase_id=p0.id, text="existing", type="read", status="todo", position=0))
    a = Assessment(concept_id=concept.id, kind="self_explanation", prompt="p",
                   score=0.3, gaps=gaps)
    session.add(a)
    session.commit()
    return topic, track, concept, p0, p1, a


def _llm(items, revisit=None):
    return ScriptedLLMClient([LLMResponse(text=json.dumps(
        {"items": items, "revisit": revisit}))])


def test_remediate_injects_items_into_current_phase(session):
    topic, track, concept, p0, p1, a = _seed(session, ["gap A", "gap B"])
    llm = _llm([{"type": "build", "text": "attack A"}, {"type": "write", "text": "attack B"}])
    res = remediate_concept(session, concept, llm=llm)
    assert len(res.items) == 2
    placed = session.exec_all(Item) if hasattr(session, "exec_all") else None  # see Step 3 note
    rem = [i for i in session.query(Item).all()] if placed is None else placed
    rem = [i for i in rem if i.added_by == "remediation"]
    assert len(rem) == 2
    assert all(i.phase_id == p0.id for i in rem)  # current phase = earliest unfinished
    assert all(i.concept_refs == ["softmax"] for i in rem)
    kinds = {e.kind for e in res.events}
    assert {"remediate:probe", "remediate:generated", "remediate:placed",
            "remediate:done"} <= kinds


def test_remediate_is_idempotent_for_same_gaps(session):
    topic, track, concept, p0, p1, a = _seed(session, ["gap A"])
    res1 = remediate_concept(session, concept, llm=_llm([{"type": "build", "text": "x"}]))
    assert len(res1.items) == 1
    # Same unresolved gap, fresh call -> nothing new injected.
    res2 = remediate_concept(session, concept, llm=_llm([{"type": "build", "text": "y"}]))
    assert res2.items == []


def test_remediate_new_gap_injects_even_with_old_open(session):
    topic, track, concept, p0, p1, a = _seed(session, ["gap A"])
    remediate_concept(session, concept, llm=_llm([{"type": "build", "text": "x"}]))
    a2 = Assessment(concept_id=concept.id, kind="self_explanation", prompt="p",
                    score=0.3, gaps=["gap A", "gap C"])
    session.add(a2)
    session.commit()
    res = remediate_concept(session, concept, llm=_llm([{"type": "build", "text": "z"}]))
    assert len(res.items) == 1  # only the new gap C


def test_remediate_revisit_lands_in_later_phase(session):
    topic, track, concept, p0, p1, a = _seed(session, ["gap A"])
    res = remediate_concept(session, concept,
                            llm=_llm([{"type": "build", "text": "x"}],
                                     revisit={"text": "revisit softmax"}))
    revisits = [i for i in res.items if i.remediation_key.startswith("revisit:")]
    assert len(revisits) == 1
    assert revisits[0].phase_id == p1.id


def test_remediate_raises_without_assessment(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="bare")
    session.add(concept)
    session.commit()
    try:
        remediate_concept(session, concept, llm=_llm([]))
        assert False, "expected RemediationError"
    except RemediationError:
        pass
```

NOTE for the implementer: use `sqlmodel.select` + `session.exec(...)` for queries (match
the codebase). Replace the `session.query(...)` placeholder in the first test with
`session.exec(select(Item)).all()` and add `from sqlmodel import select`. Return the
persisted `Item` rows in `RemediationResult.items` so `res.items` carries `phase_id`,
`remediation_key`, `added_by`.

- [ ] **Step 2: Run, expect fail.**

- [ ] **Step 3: Implement the orchestrator** — append to `engine/remediate.py`:

```python
from sqlmodel import Session, select

from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent, Assessment, Concept, Item, KnowledgeEstimate, Phase, SourceDoc,
    TopicFoundation, Track,
)


class RemediationError(Exception):
    """No assessment to remediate from (route maps to HTTP 400)."""


@dataclass
class RemediationResult:
    items: list[Item]
    events: list["AgentEvent"]


def _latest_assessment(session: Session, concept_id: int,
                       assessment_id: int | None) -> Assessment | None:
    if assessment_id is not None:
        return session.get(Assessment, assessment_id)
    return session.exec(
        select(Assessment).where(Assessment.concept_id == concept_id)
        .order_by(Assessment.id.desc())).first()


def _covered_keys(session: Session, track_id: int, concept_name: str) -> set[str]:
    """remediation_keys of still-OPEN remediation items referencing this concept."""
    rows = session.exec(
        select(Item).join(Phase).where(Phase.track_id == track_id)).all()
    return {
        it.remediation_key for it in rows
        if it.added_by == "remediation" and it.status != "done"
        and concept_name in (it.concept_refs or [])
    }


def remediate_concept(session: Session, concept: Concept, *,
                      llm: LLMClient, assessment_id: int | None = None) -> RemediationResult:
    track = session.get(Track, concept.track_id)
    topic_id = track.topic_id
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic_id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    assessment = _latest_assessment(session, concept.id, assessment_id)
    if assessment is None:
        raise RemediationError("no assessment to remediate from")

    covered = _covered_keys(session, track.id, concept.name)
    open_gaps = [g for g in (assessment.gaps or []) if gap_key(g) not in covered]
    emit("remediate:probe", f"{len(open_gaps)} open gap(s)")
    if not open_gaps:
        emit("remediate:done", "nothing to remediate")
        session.commit()
        return RemediationResult(items=[], events=events)

    estimate = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept.id)).first()
    level = estimate.level if estimate else "high"
    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)).first()
    sources = session.exec(
        select(SourceDoc).where(SourceDoc.topic_id == topic_id,
                                SourceDoc.status == "accepted")).all()
    sources_summary = "; ".join(s.title for s in sources)

    system, user = build_remediate_prompt(
        concept.name, open_gaps, level,
        foundation_overview=(foundation.overview if foundation else ""),
        sources_summary=sources_summary)
    draft = parse_remediation_json(
        llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[]).text)

    planned = plan_remediation_items(draft.items, concept.name, open_gaps, covered)
    emit("remediate:generated", f"{len(planned)} item(s)")

    phases = session.exec(
        select(Phase).where(Phase.track_id == track.id).order_by(Phase.position)).all()
    statuses = [
        [it.status for it in session.exec(
            select(Item).where(Item.phase_id == p.id)).all()]
        for p in phases
    ]
    target_idx = choose_target_phase(statuses)
    target = phases[target_idx]
    base_pos = len(statuses[target_idx])

    created: list[Item] = []
    for offset, pi in enumerate(planned):
        item = Item(phase_id=target.id, text=pi.text, type=pi.type,
                    position=base_pos + offset, concept_refs=pi.concept_refs,
                    added_by="remediation", remediation_key=pi.remediation_key)
        session.add(item)
        created.append(item)
    emit("remediate:placed", f"phase {target.position}")

    revisit_key = f"revisit:{gap_key(concept.name)}"
    if draft.revisit and revisit_key not in covered:
        later = phases[target_idx + 1] if target_idx + 1 < len(phases) else target
        rtext = str(draft.revisit.get("text") or "").strip() or \
            f"Revisit & self-explain: {concept.name}"
        rpos = len(session.exec(select(Item).where(Item.phase_id == later.id)).all())
        ritem = Item(phase_id=later.id, text=rtext, type="write", position=rpos,
                     concept_refs=[concept.name], added_by="remediation",
                     remediation_key=revisit_key)
        session.add(ritem)
        created.append(ritem)

    emit("remediate:done", f"concept {concept.id}")
    session.commit()
    for it in created:
        session.refresh(it)
    return RemediationResult(items=created, events=events)
```

Move the imports added in this step to the top of the module with the others (keep the file's imports grouped). Then:

- [ ] **Step 4: Run, expect pass** — fix the test's `session.query` placeholder to `session.exec(select(Item)).all()` as noted.

- [ ] **Step 5: Run the full backend suite** — `uv run pytest -q` → all prior tests still green.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "feat(remediate): orchestrator with idempotent injection + revisit"`

---

## Task 5: API route + schemas + registration

**Files:**
- Modify: `src/adaptive_academy/api/schemas.py`
- Create: `src/adaptive_academy/api/routes_remediate.py`
- Modify: `src/adaptive_academy/api/app.py`
- Modify: `src/adaptive_academy/api/routes_topics.py` (`_curriculum_out`)
- Modify: `src/adaptive_academy/api/routes_items.py` (`patch_item`)
- Test: `tests/test_api_remediate.py`

- [ ] **Step 1: Write failing API tests** — `tests/test_api_remediate.py`:

```python
import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, Item, Phase, Topic, Track,
)


def _seed(session, gaps):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    p = Phase(track_id=track.id, title="P0", position=0)
    session.add(p)
    session.commit()
    session.add(Item(phase_id=p.id, text="existing", type="read", status="todo", position=0))
    session.add(Assessment(concept_id=concept.id, kind="self_explanation", prompt="p",
                           score=0.3, gaps=gaps))
    session.commit()
    return topic.id, concept.id


def _override_llm(items):
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps({"items": items, "revisit": None}))])


def test_remediate_happy_path_and_idempotent(session):
    app.dependency_overrides[get_session] = lambda: session
    topic_id, cid = _seed(session, ["gap A"])
    _override_llm([{"type": "build", "text": "attack A"}])
    client = TestClient(app)

    r = client.post(f"/api/concepts/{cid}/remediate", json={})
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1 and body["items"][0]["is_remediation"] is True

    # Re-running for the same unresolved gap injects nothing.
    _override_llm([{"type": "build", "text": "again"}])
    r2 = client.post(f"/api/concepts/{cid}/remediate", json={})
    assert r2.status_code == 200 and r2.json()["items"] == []

    # The remediation item shows on the track, flagged.
    cur = client.get(f"/api/topics/{topic_id}/curriculum").json()
    flagged = [it for p in cur["phases"] for it in p["items"] if it["is_remediation"]]
    assert len(flagged) == 1
    app.dependency_overrides.clear()


def test_remediate_404_unknown_concept(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([])
    client = TestClient(app)
    assert client.post("/api/concepts/9999/remediate", json={}).status_code == 404
    app.dependency_overrides.clear()


def test_remediate_400_without_assessment(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([])  # 400 before LLM
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="bare")
    session.add(concept)
    session.commit()
    client = TestClient(app)
    r = client.post(f"/api/concepts/{concept.id}/remediate", json={})
    assert r.status_code == 400
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run, expect fail** — 404 (route missing) / ImportError.

- [ ] **Step 3: Add schemas** — in `schemas.py`, add `is_remediation` to `ItemOut` and add the new models:

```python
class ItemOut(BaseModel):
    id: int
    text: str
    type: str
    status: str
    position: int
    is_remediation: bool = False
```

Append near the assess/retention schemas:

```python
class RemediateIn(BaseModel):
    from_assessment_id: Optional[int] = None


class RemediationOut(BaseModel):
    items: list[ItemOut]
    events: list[EventOut]
```

- [ ] **Step 4: Create the route** — `src/adaptive_academy/api/routes_remediate.py`:

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import EventOut, ItemOut, RemediateIn, RemediationOut
from adaptive_academy.engine.remediate import RemediationError, remediate_concept
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Concept, Item

router = APIRouter(prefix="/api/concepts", tags=["remediate"])


def _item_out(i: Item) -> ItemOut:
    return ItemOut(id=i.id, text=i.text, type=i.type, status=i.status,
                   position=i.position, is_remediation=i.added_by == "remediation")


@router.post("/{concept_id}/remediate", response_model=RemediationOut)
def remediate(concept_id: int, body: RemediateIn,
              session: Session = Depends(get_session),
              llm: LLMClient = Depends(get_llm)) -> RemediationOut:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    try:
        result = remediate_concept(session, concept, llm=llm,
                                   assessment_id=body.from_assessment_id)
    except RemediationError as e:
        raise HTTPException(400, str(e))
    return RemediationOut(items=[_item_out(i) for i in result.items],
                          events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events])
```

- [ ] **Step 5: Register the router** — in `api/app.py`, add the import alongside the others and `app.include_router(...)` with the rest:

```python
from adaptive_academy.api.routes_remediate import router as remediate_router
```
```python
    app.include_router(remediate_router)
```

- [ ] **Step 6: Set `is_remediation` everywhere ItemOut is built.** In `routes_topics.py` `_curriculum_out`, change the item construction to:

```python
            items=[ItemOut(id=i.id, text=i.text, type=i.type, status=i.status,
                           position=i.position, is_remediation=i.added_by == "remediation")
                   for i in items],
```

In `routes_items.py` `patch_item`, change the return to:

```python
    return ItemOut(id=item.id, text=item.text, type=item.type, status=item.status,
                   position=item.position, is_remediation=item.added_by == "remediation")
```

- [ ] **Step 7: Run, expect pass** — `uv run pytest tests/test_api_remediate.py -q`.

- [ ] **Step 8: Full suite** — `uv run pytest -q` all green.

- [ ] **Step 9: Commit** — `git add -A && git commit -m "feat(remediate): POST /api/concepts/{id}/remediate + is_remediation"`

---

## Task 6: Markdown round-trip safety + integration loop

**Files:**
- Test: `tests/test_track_markdown.py` (append), `tests/test_integration_remediate_loop.py`

- [ ] **Step 1: Round-trip test with a remediation item** — append to `tests/test_track_markdown.py`:

```python
def test_round_trip_preserves_items_regardless_of_origin():
    # A remediation item is a normal ItemView for serialization purposes (added_by is
    # DB-only, like concept_refs). The canonical text/type/status must survive round-trip.
    from adaptive_academy.engine.track_markdown import (
        ItemView, PhaseView, TrackView, markdown_to_track, track_to_markdown,
    )
    tv = TrackView(title="T", phases=[PhaseView(
        title="P0", items=[ItemView(text="Remediate: gap A", type="build", status="todo")])])
    back = markdown_to_track(track_to_markdown(tv))
    assert back.phases[0].items[0].text == "Remediate: gap A"
    assert back.phases[0].items[0].type == "build"
```

- [ ] **Step 2: Run, expect pass** (no code change — proves the contract holds). If it fails, STOP and report; do not alter the parser without escalation.

- [ ] **Step 3: Integration loop test** — `tests/test_integration_remediate_loop.py`. Mirror `test_integration_assess_loop.py`: seed a topic/track/phase/concept at `high`, run a weak assessment (rubric requires "softmax"; learner omits it → estimate `low`, gaps recorded), then remediate and assert a remediation item referencing the concept now exists in the track:

```python
import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Concept, Item, KnowledgeEstimate, Phase, Topic, TopicFoundation, Track,
)


def test_weak_assessment_then_remediate_injects_targeted_item(session):
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="Build LLMs")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["softmax"], prerequisite_map={}))
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    phase = Phase(track_id=track.id, title="P0", position=0)
    session.add(phase)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
    session.add(Item(phase_id=phase.id, text="read about softmax", type="read",
                     status="todo", position=0))
    session.commit()
    client = TestClient(app)

    # Weak anchored assessment -> estimate low, gap recorded.
    rubric = json.dumps({"criteria": ["c"], "must_include": ["subtract the max"],
                         "strong_signs": [], "weak_signs": [], "source_refs": []})
    grade = json.dumps({"score": 0.3, "verdict": "weak", "gaps": ["hand-wavy"]})
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=rubric), LLMResponse(text=grade)])
    a = client.post(f"/api/concepts/{concept.id}/assess",
                    json={"kind": "self_explanation", "response": "it normalizes"})
    assert a.status_code == 200 and a.json()["estimate_level"] == "low"

    # Remediate -> targeted item injected, flagged, referencing the concept.
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([LLMResponse(text=json.dumps(
        {"items": [{"type": "build", "text": "Implement numerically-stable softmax"}],
         "revisit": None}))])
    r = client.post(f"/api/concepts/{concept.id}/remediate", json={})
    assert r.status_code == 200 and len(r.json()["items"]) == 1

    rem = [i for i in session.exec_items() ] if False else None  # see note
    from sqlmodel import select
    items = session.exec(select(Item)).all()
    rem = [i for i in items if i.added_by == "remediation"]
    assert len(rem) == 1
    assert "softmax" in rem[0].concept_refs
    app.dependency_overrides.clear()
```

Remove the dead `session.exec_items()` placeholder line when implementing; it documents that the query uses `session.exec(select(Item)).all()`.

- [ ] **Step 4: Run, expect pass** — `uv run pytest tests/test_integration_remediate_loop.py tests/test_track_markdown.py -q`.

- [ ] **Step 5: Full suite + ruff** — `uv run pytest -q && uv run ruff check .` both clean.

- [ ] **Step 6: Commit** — `git add -A && git commit -m "test(remediate): round-trip safety + full adaptive-loop integration"`

---

## Task 7: Frontend — flag remediation items + Remediate affordance

**Files:**
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`
- Modify: `frontend/src/routes/topics/[id]/track/+page.svelte`
- Modify: `frontend/src/routes/topics/[id]/assess/+page.svelte`
- Test: a vitest spec under `frontend/` mirroring existing frontend tests (check `frontend/` for the existing test location/pattern first).

- [ ] **Step 1: Inspect existing frontend tests** — find how the 7 frontend tests are structured (`find frontend -name "*.test.ts" -o -name "*.spec.ts"`) and mirror that pattern/location for the new test.

- [ ] **Step 2: Types** — in `types.ts`, add `is_remediation?: boolean;` to the `Item` interface and add:

```typescript
export interface Remediation { items: Item[]; events: EventOut[]; }
```

- [ ] **Step 3: API client** — in `api.ts`, add:

```typescript
  remediate: (conceptId: number, from_assessment_id?: number) =>
    fetch(`/api/concepts/${conceptId}/remediate`, {
      method: 'POST', headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ from_assessment_id })
    }).then(j<Remediation>),
```

Import `Remediation` in the type import list at the top of `api.ts`.

- [ ] **Step 4: Flag remediation items on the track page** — in `track/+page.svelte`, in the item `<li>`, add a chip + tint when `it.is_remediation`:

```svelte
            <li class="flex gap-2 items-center text-sm {it.is_remediation ? 'bg-amber-50 rounded px-1' : ''}">
              <button class="font-mono text-xs border rounded px-1"
                      onclick={() => toggle(it.id, it.status)}>{it.status}</button>
              <span class="text-xs text-gray-500">({it.type})</span>
              <span>{it.text}</span>
              {#if it.is_remediation}<span class="text-xs bg-amber-200 rounded px-1">remediation</span>{/if}
            </li>
```

- [ ] **Step 5: Remediate affordance after a weak assessment** — in `assess/+page.svelte`, inside the `{#if result}` block, when `result.gaps.length` add a button that remediates and reports. Add to the `<script>`:

```typescript
  let remediating = $state(false);
  let remediatedCount = $state<number | null>(null);
  async function remediate() {
    if (conceptId == null) return;
    remediating = true;
    try {
      const r = await api.remediate(conceptId);
      remediatedCount = r.items.length;
    } finally { remediating = false; }
  }
```

In the result section, after the gaps `<ul>`, add:

```svelte
        {#if result.gaps.length}
          <button class="border rounded px-3 py-1 text-sm self-start disabled:opacity-50"
                  onclick={remediate} disabled={remediating}>
            {remediating ? 'Remediating…' : 'Remediate these gaps'}
          </button>
          {#if remediatedCount != null}
            <p class="text-xs text-gray-600">
              {remediatedCount > 0
                ? `Injected ${remediatedCount} item(s) — see the track.`
                : 'Already covered by an open remediation item.'}
              <a class="underline" href="/topics/{topicId}/track">Open track →</a>
            </p>
          {/if}
        {/if}
```

Import `Remediation` type only if needed (the call is typed through `api`). Ensure `api` is already imported (it is).

- [ ] **Step 6: Write a vitest spec** mirroring the existing pattern: assert that an `Item` with `is_remediation: true` renders the "remediation" chip on the track page (or, if existing tests are pure-logic rather than component-render, add a small unit test for the `api.remediate` URL/shape consistent with the existing tests). Keep it consistent with what's already there — do not introduce a new test style.

- [ ] **Step 7: Run frontend tests** — in `frontend/`: `npm test` (or the project's test script — check `frontend/package.json`). All green.

- [ ] **Step 8: Commit** — `git add -A && git commit -m "feat(remediate): flag remediation items + Remediate affordance (frontend)"`

---

## Task 8: Final verification

- [ ] **Step 1:** `uv run pytest -q` — expect 87 prior + new backend tests, all green.
- [ ] **Step 2:** `uv run ruff check .` — clean.
- [ ] **Step 3:** `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head` — clean.
- [ ] **Step 4:** `just seed && uv run alembic downgrade -1 && uv run alembic upgrade head` — clean after seed.
- [ ] **Step 5:** Frontend tests green.
- [ ] **Step 6:** Dispatch the final adversarial code reviewer over the whole branch diff, then proceed to `superpowers:finishing-a-development-branch` (merge to main + push — the user's standing preference).

---

## Self-Review (author)

- **Spec coverage:** endpoint (Task 5) ✓; 400/404 (Task 5) ✓; evidence-keyed prompt (Task 3) ✓; non-destructive append + idempotency (Tasks 2,4) ✓; marker column + migration (Task 1) ✓; UI flag + affordance (Task 7) ✓; round-trip safety (Task 6) ✓; integration loop (Task 6) ✓; observability events (Task 4) ✓; additive migration round-trips (Tasks 1,8) ✓.
- **Type consistency:** `PlacedItem` fields (text/type/concept_refs/remediation_key/added_by) used consistently across Tasks 2 & 4; `remediate_concept(session, concept, *, llm, assessment_id=None)` signature stable across Tasks 4 & 5; `RemediationResult.items` are persisted `Item` rows (carry `phase_id`/`added_by`/`remediation_key`); `ItemOut.is_remediation` set in every builder (Task 5).
- **Idempotency vs. convergence:** dedup is keyed on *open* remediation_keys (status ≠ done), so completing a remediation item lets a recurring gap be re-injected later — intended (re-teach on regression), and avoids the "never converges" trap by only counting OPEN items as covered.
- **Placeholder scan:** the two test placeholders (`session.query`, `session.exec_items()`) are explicitly called out with the exact `session.exec(select(Item)).all()` replacement — implementer must apply.
