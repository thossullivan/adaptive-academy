# Map Revision Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Learnings-aware program-map revision — a paid research pass that produces a reviewable, additive-first diff (add/revise/prune milestones and topics), with a gate-passed nudge.

**Architecture:** New `engine/revision.py` holds a pure learnings digest, a 3-angle freshness fan-out (reusing `engine/fanout.py::fan_out_with_retry`), a forced-tool-use diff synthesis, shared parse/apply validation, and per-change apply functions. Two new tables (`MapRevision`, `MapChange`) store the diff; two additive columns (`Milestone.archived`, `ProgramTopicLink.added_by`) support prune/provenance. `engine/gates.py` emits a `program:gate_passed` event on status transition, powering a `revision_suggested` flag. Four new API routes; the `/programs/[id]` page gains a revision panel and banner; the Today strip gains the nudge.

**Tech Stack:** Python/FastAPI/SQLModel/SQLite + Alembic, `structured_json` forced-tool-use seam, SvelteKit 5 + Tailwind, pytest + vitest.

**Spec:** `docs/superpowers/specs/2026-07-10-map-revision.md`.

## Global Constraints

- Started or passed work is **untouchable**: `revise_milestone`/`prune_milestone` never target a milestone that has a started link OR `gate_status == "passed"`; `prune_topic` never targets a started link. Enforced by ONE shared validation function used at parse time AND apply time (spec §2.3, §4.2.5, §4.3).
- Prunes never delete rows: `prune_topic` → `status="pruned"`; `prune_milestone` → `archived=true` (spec §4.3).
- Only ONE open revision at a time: `POST /revise` → 400 while any `MapChange.status == "proposed"` exists (spec §4.2.1).
- Zero-sources guard reused verbatim from initial research: commit trace events, raise `ValueError`, persist no revision (spec §4.2.3).
- All revision trace events carry `program_id` only; kinds `program_revision:plan | subagent | subagent_retry | subagent_error | changes_dropped` plus `prompt` (spec §4.2).
- `program:gate_passed` is emitted ONLY on a transition to passed, not on re-evaluation that stays passed (spec §4.4, §7).
- Archived milestones: hidden in the FE rail behind a toggle, skipped by the learnings digest, and their gate endpoint returns 400 "milestone archived" (spec §4.3 "excluded from rail, DAG, gates").
- New prompt lives in `adaptive_academy/prompts.py` as a version-tagged `Prompt`; `.tag` emitted as `AgentEvent(kind="prompt")` before the LLM call.
- Frontend: svelte-check has a **22-error pre-existing baseline** (old `api.test.ts` lines) — "clean" = at most 22 errors, none in files this plan touches.
- Verification commands: `uv run pytest -q`, `uv run ruff check .`, `cd frontend && npx vitest run && npx svelte-check && npm run build`, `uv run alembic upgrade head`.
- Commits follow `feat:`/`fix:`/`test:` style and end with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

---

### Task 1: Models + migration

**Files:**
- Modify: `src/adaptive_academy/models.py` (append 2 tables; add 1 field each to `Milestone` and `ProgramTopicLink`)
- Create: `alembic/versions/<generated>_map_revision_tables.py`
- Test: `tests/test_revision_models.py`

**Interfaces:**
- Produces: `MapRevision(id, program_id, map_health, created_at)`; `MapChange(id, revision_id, kind, payload: dict, why, source_urls: list[str], status="proposed", created_at)`; `Milestone.archived: bool = False`; `ProgramTopicLink.added_by: str = "research"`. All later tasks import these from `adaptive_academy.models`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_revision_models.py
from sqlmodel import select

from adaptive_academy.models import (
    MapChange,
    MapRevision,
    Milestone,
    Program,
    ProgramTopicLink,
)


def test_map_revision_tables_roundtrip(session):
    program = Program(title="P", goal_statement="g")
    session.add(program)
    session.commit()

    rev = MapRevision(program_id=program.id, map_health="field moved to MoE")
    session.add(rev)
    session.commit()
    session.refresh(rev)
    assert rev.created_at is not None

    change = MapChange(
        revision_id=rev.id,
        kind="add_topic",
        payload={"milestone_id": 1, "title": "MoE routing"},
        why="new frontier",
        source_urls=["https://example.com/moe"],
    )
    session.add(change)
    session.commit()
    session.refresh(change)
    assert change.status == "proposed"
    assert change.payload == {"milestone_id": 1, "title": "MoE routing"}
    assert change.source_urls == ["https://example.com/moe"]


def test_new_columns_default(session):
    program = Program(title="P", goal_statement="g")
    session.add(program)
    session.commit()
    m = Milestone(program_id=program.id, title="M", order_index=0)
    link = ProgramTopicLink(milestone_id=1, proposed_title="T")
    session.add(m)
    session.add(link)
    session.commit()
    session.refresh(m)
    session.refresh(link)
    assert m.archived is False
    assert link.added_by == "research"
    assert session.exec(select(Milestone).where(Milestone.archived == False)).all()  # noqa: E712
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_revision_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'MapRevision'`

- [ ] **Step 3: Implement the models**

In `src/adaptive_academy/models.py`: add to `Milestone` (after `override_reason: str = ""`):

```python
    archived: bool = False
```

Add to `ProgramTopicLink` (after `sources: ...`):

```python
    added_by: str = "research"  # "research" | "revision"
```

Append at the end of the file:

```python
class MapRevision(SQLModel, table=True):
    """One learnings-aware map-revision pass (spec 2026-07-10-map-revision §3)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    program_id: int = Field(foreign_key="program.id")
    map_health: str = ""
    created_at: datetime = Field(default_factory=_now)


class MapChange(SQLModel, table=True):
    """A single proposed map change awaiting per-change accept/reject."""

    id: Optional[int] = Field(default=None, primary_key=True)
    revision_id: int = Field(foreign_key="maprevision.id")
    kind: str  # add_topic | add_milestone | revise_milestone | prune_topic | prune_milestone
    payload: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    why: str = ""
    source_urls: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    status: str = "proposed"  # proposed | accepted | rejected
    created_at: datetime = Field(default_factory=_now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_revision_models.py -q`
Expected: 2 passed

- [ ] **Step 5: Create the migration**

Run `uv run alembic revision -m "map revision tables"`, keep the generated id, set `down_revision = "5e252d8109c0"`:

```python
"""map revision tables

Revision ID: <generated>
Revises: 5e252d8109c0
Create Date: 2026-07-10
"""
from alembic import op
import sqlalchemy as sa

revision = "<generated>"
down_revision = "5e252d8109c0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "maprevision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=False),
        sa.Column("map_health", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "mapchange",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("maprevision.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("why", sa.String(), nullable=False, server_default=""),
        sa.Column("source_urls", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("milestone") as batch:
        batch.add_column(sa.Column("archived", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
    with op.batch_alter_table("programtopiclink") as batch:
        batch.add_column(sa.Column("added_by", sa.String(), nullable=False,
                                   server_default="research"))


def downgrade() -> None:
    with op.batch_alter_table("programtopiclink") as batch:
        batch.drop_column("added_by")
    with op.batch_alter_table("milestone") as batch:
        batch.drop_column("archived")
    op.drop_table("mapchange")
    op.drop_table("maprevision")
```

- [ ] **Step 6: Verify migration round-trips**

Run: `uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head`
Expected: exit 0 each. Then `uv run pytest -q` (full suite green) and `uv run ruff check .` (clean).

- [ ] **Step 7: Commit**

```bash
git add src/adaptive_academy/models.py alembic/versions/*map_revision* tests/test_revision_models.py
git commit -m "feat(revision): MapRevision/MapChange tables + Milestone.archived + link provenance"
```

---

### Task 2: Learnings digest (pure) + public gate/alias helpers

**Files:**
- Modify: `src/adaptive_academy/engine/gates.py` (rename `_milestone_load_bearing` → `milestone_load_bearing`, update its one internal caller)
- Modify: `src/adaptive_academy/engine/aliases.py` (rename `_group_level` → `group_level`, update its one internal caller)
- Create: `src/adaptive_academy/engine/revision.py` (digest only in this task)
- Test: `tests/test_revision_digest.py`

**Interfaces:**
- Consumes: `evaluate_concept`, `milestone_load_bearing` from `engine.gates`; `group_level`, `normalize_name` from `engine.aliases`.
- Produces: `build_learnings_digest(session: Session, program: Program) -> str` — deterministic, no LLM, skips archived milestones. Later tasks embed its output in the synthesis prompt.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_revision_digest.py
from datetime import datetime, timedelta

from adaptive_academy.engine.revision import build_learnings_digest
from adaptive_academy.models import (
    Assessment, Concept, ConceptAlias, KnowledgeEstimate, Milestone, Program,
    ProgramTopicLink, Topic, Track,
)

T0 = datetime(2026, 7, 1)


def _program_with_two_legs(session):
    p = Program(title="PhD prep", goal_statement="research-ready")
    session.add(p)
    session.commit()
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0,
                   gate_status="passed")
    m2 = Milestone(program_id=p.id, title="Architectures", order_index=1)
    m3 = Milestone(program_id=p.id, title="Old leg", order_index=2, archived=True)
    session.add(m1); session.add(m2); session.add(m3)
    topic = Topic(title="Backprop")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Backprop")
    session.add(track)
    session.commit()
    c = Concept(track_id=track.id, name="Chain rule", is_load_bearing=True)
    session.add(c)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=c.id, level="medium"))
    session.add(Assessment(concept_id=c.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=c.id, kind="recall", prompt="p", score=0.85,
                           created_at=T0 + timedelta(days=8)))
    session.add(ProgramTopicLink(milestone_id=m1.id, topic_id=topic.id, status="started"))
    session.add(ProgramTopicLink(milestone_id=m2.id, proposed_title="Attention", status="stub"))
    session.add(ConceptAlias(program_id=p.id, canonical_name="chain rule", concept_id=c.id))
    session.commit()
    return p


def test_digest_covers_legs_evidence_and_knowledge(session):
    p = _program_with_two_legs(session)
    digest = build_learnings_digest(session, p)
    assert "LEG 1: Foundations [gate: passed]" in digest
    assert "1 started" in digest
    assert "Chain rule=verified" in digest       # per-concept evidence verdict
    assert "LEG 2: Architectures [gate: open]" in digest
    assert "1 stub" in digest
    assert "chain rule=medium" in digest         # alias-group knowledge level
    assert "Old leg" not in digest               # archived legs skipped


def test_digest_is_deterministic_and_handles_empty(session):
    p = Program(title="Empty", goal_statement="g")
    session.add(p)
    session.commit()
    d1 = build_learnings_digest(session, p)
    d2 = build_learnings_digest(session, p)
    assert d1 == d2
    assert "no milestones yet" in d1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_revision_digest.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'adaptive_academy.engine.revision'`

- [ ] **Step 3: Implement**

In `src/adaptive_academy/engine/gates.py`: rename `_milestone_load_bearing` to `milestone_load_bearing` (definition + its one call inside `milestone_gate`).

In `src/adaptive_academy/engine/aliases.py`: rename `_group_level` to `group_level` (definition + its one call inside `apply_program_aliases`).

Create `src/adaptive_academy/engine/revision.py`:

```python
"""Map Revision — learnings-aware re-research for a Program's milestone map.

This module owns: the deterministic learnings digest (this task), and (later
tasks) the 3-angle freshness pass, diff synthesis, and per-change apply logic.
Spec: docs/superpowers/specs/2026-07-10-map-revision.md
"""

from collections import Counter

from sqlmodel import Session, select

from adaptive_academy.engine.aliases import group_level
from adaptive_academy.engine.gates import evaluate_concept, milestone_load_bearing
from adaptive_academy.models import (
    Assessment,
    ConceptAlias,
    Milestone,
    Program,
    ProgramTopicLink,
)


def build_learnings_digest(session: Session, program: Program) -> str:
    """Deterministic, no-LLM summary of what the learner has proven so far.

    Feeds the revision synthesis prompt. Skips archived milestones. Uses the
    same evidence verdicts the gates use — the digest and the gate never
    disagree about what is verified.
    """
    lines = [f"PROGRAM: {program.title} — status {program.status}"]
    milestones = session.exec(
        select(Milestone)
        .where(Milestone.program_id == program.id, Milestone.archived == False)  # noqa: E712
        .order_by(Milestone.order_index)
    ).all()
    if not milestones:
        lines.append("no milestones yet")
        return "\n".join(lines)

    for i, m in enumerate(milestones, start=1):
        links = session.exec(
            select(ProgramTopicLink).where(ProgramTopicLink.milestone_id == m.id)
        ).all()
        counts = Counter(link.status for link in links)
        count_str = ", ".join(
            f"{counts[s]} {s}" for s in ("started", "stub", "proposed", "pruned") if counts[s]
        ) or "no topics"
        lines.append(f"LEG {i}: {m.title} [gate: {m.gate_status}] — topics: {count_str}")
        concepts = milestone_load_bearing(session, m)
        if concepts:
            verdicts = []
            for c in sorted(concepts, key=lambda c: c.name):
                rows = session.exec(
                    select(Assessment).where(Assessment.concept_id == c.id)
                ).all()
                verdicts.append(f"{c.name}={evaluate_concept(c.id, c.name, rows).verdict}")
            lines.append("  evidence: " + ", ".join(verdicts))

    aliases = session.exec(
        select(ConceptAlias).where(ConceptAlias.program_id == program.id)
    ).all()
    groups: dict[str, list[int]] = {}
    for a in aliases:
        groups.setdefault(a.canonical_name, []).append(a.concept_id)
    if groups:
        knowledge = []
        for name in sorted(groups):
            level = group_level(session, groups[name])
            if level:
                knowledge.append(f"{name}={level}")
        if knowledge:
            lines.append("KNOWLEDGE (alias groups): " + ", ".join(knowledge))
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_revision_digest.py -q` — Expected: 2 passed.
Then `uv run pytest -q` (renames must not break gates/aliases suites) and `uv run ruff check .`.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/ tests/test_revision_digest.py
git commit -m "feat(revision): deterministic learnings digest (gate-consistent evidence)"
```

---

### Task 3: Revision pass — prompt, angles, schema, validation, orchestrator

**Files:**
- Modify: `src/adaptive_academy/prompts.py` (append `PROGRAM_REVISION`)
- Modify: `src/adaptive_academy/engine/revision.py` (append everything below the digest)
- Test: `tests/test_revision_pass.py`

**Interfaces:**
- Consumes: `fan_out_with_retry` from `engine.fanout`; `structured_json`; `build_learnings_digest` (Task 2); Task 1 models.
- Produces:
  - `REVISION_ANGLES: list[tuple[str, str]]` — keys `whats_new`, `curricula_check`, `frontier_shifts`; templates take `{goal}`, `{focus}`, `{since}`
  - `build_revision_briefs(goal: str, focus: str, since_label: str) -> list[SearchBrief]`
  - `serialize_map(session, program) -> str` (ids + statuses, archived excluded)
  - `validate_change(session, program: Program, kind: str, payload: dict) -> str | None` — returns a drop/refusal reason or None; THE shared parse-time/apply-time gate
  - `run_revision(session, program, intent, *, researcher, llm, max_workers=3) -> RevisionResult(revision: MapRevision, changes: list[MapChange], events: list[AgentEvent])` — raises `ValueError` on open revision or zero sources
  - `REVISION_SCHEMA: dict`

- [ ] **Step 1: Add the prompt**

Append to `src/adaptive_academy/prompts.py`:

```python
PROGRAM_REVISION = Prompt(
    "program_revision",
    1,
    """You are the CurriculumDirector REVISING an existing long-horizon program map.
You receive: the CURRENT MAP (milestones and topics with database ids and statuses),
a LEARNINGS DIGEST (verified evidence about what the learner has actually retained),
and fresh SOURCES about how the field has moved since the map was drawn.

Propose a SHORT list of targeted changes — not a new map. Allowed kinds:
- add_topic: a new weeks-scale topic inside an existing milestone (payload:
  milestone_id, title)
- add_milestone: a new leg (payload: after_milestone_id or null for first,
  title, success_criteria phrased VERIFIABLY, topics: [{title, why}])
- revise_milestone: retitle / re-criteria an UNSTARTED leg (payload:
  milestone_id, title and/or success_criteria)
- prune_topic: drop an unstarted topic the learner verifiably no longer needs
  (payload: link_id)
- prune_milestone: archive an unstarted leg made obsolete (payload: milestone_id)

Rules:
- NEVER target milestones with started topics or a passed gate, or started links —
  such changes will be discarded.
- Every change needs a concrete "why" grounded in the digest or the sources, and
  the source URLs that justify it (empty list only for digest-grounded changes).
- Also return map_health: one paragraph on how well the current map matches the
  field and the learner's demonstrated knowledge.
- Prefer few high-value changes over many speculative ones. Return via the tool
  call, nothing else.""",
)
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_revision_pass.py
import json

import pytest
from sqlmodel import select

from adaptive_academy.engine.revision import (
    REVISION_ANGLES,
    build_revision_briefs,
    run_revision,
    serialize_map,
    validate_change,
)
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    MapChange, MapRevision, Milestone, Program, ProgramIntent, ProgramTopicLink,
)


def _program(session, *, started_first_leg=True):
    p = Program(title="PhD prep", goal_statement="research-ready")
    session.add(p)
    session.commit()
    session.add(ProgramIntent(program_id=p.id, focus_area="custom LLMs"))
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0,
                   gate_status="passed")
    m2 = Milestone(program_id=p.id, title="Architectures", order_index=1)
    session.add(m1); session.add(m2)
    session.commit()
    l1 = ProgramTopicLink(milestone_id=m1.id, proposed_title="Backprop",
                          status="started" if started_first_leg else "stub")
    l2 = ProgramTopicLink(milestone_id=m2.id, proposed_title="Attention", status="stub")
    session.add(l1); session.add(l2)
    session.commit()
    return p, m1, m2, l1, l2


def test_briefs_fill_since_label():
    briefs = build_revision_briefs("PhD prep", "custom LLMs", "July 2026")
    assert [b.angle for b in briefs] == [a for a, _ in REVISION_ANGLES]
    assert "July 2026" in briefs[0].query
    assert "custom LLMs" in briefs[0].query


def test_serialize_map_carries_ids_and_statuses(session):
    p, m1, m2, l1, l2 = _program(session)
    text = serialize_map(session, p)
    assert f"milestone id={m1.id}" in text and "[gate: passed]" in text
    assert f"link id={l2.id}" in text and "(stub)" in text


def test_validate_change_rules(session):
    p, m1, m2, l1, l2 = _program(session)
    # untouchable: m1 has a started link AND a passed gate
    assert validate_change(session, p, "revise_milestone",
                           {"milestone_id": m1.id, "title": "x"}) is not None
    assert validate_change(session, p, "prune_milestone",
                           {"milestone_id": m1.id}) is not None
    assert validate_change(session, p, "prune_topic", {"link_id": l1.id}) is not None
    # allowed: un-started leg / stub link
    assert validate_change(session, p, "revise_milestone",
                           {"milestone_id": m2.id, "title": "x"}) is None
    assert validate_change(session, p, "prune_topic", {"link_id": l2.id}) is None
    # unresolvable id
    assert validate_change(session, p, "add_topic",
                           {"milestone_id": 999, "title": "x"}) is not None
    # duplicate un-started title (case-insensitive)
    assert validate_change(session, p, "add_topic",
                           {"milestone_id": m2.id, "title": "ATTENTION"}) is not None
    # unknown kind
    assert validate_change(session, p, "explode", {}) is not None


SYNTH = {
    "map_health": "solid but MoE is missing",
    "changes": [
        {"kind": "add_topic", "payload": {"milestone_id": 0, "title": "MoE routing"},
         "why": "field moved", "source_urls": ["https://e.com/moe"]},
        {"kind": "revise_milestone", "payload": {"milestone_id": -1, "title": "nope"},
         "why": "targets started leg", "source_urls": []},
    ],
}


def _synth_for(m2_id: int, m1_id: int) -> str:
    payload = json.loads(json.dumps(SYNTH))
    payload["changes"][0]["payload"]["milestone_id"] = m2_id
    payload["changes"][1]["payload"]["milestone_id"] = m1_id  # invalid: started+passed
    return json.dumps(payload)


def test_run_revision_persists_valid_changes_and_drops_invalid(session):
    p, m1, m2, l1, l2 = _program(session)
    researcher = ScriptedResearcherClient({
        "whats_new": [RawSource(title="MoE", url="https://e.com/moe", tier=1)],
    })
    llm = ScriptedLLMClient([LLMResponse(text=_synth_for(m2.id, m1.id))])
    result = run_revision(session, p, session.exec(
        select(ProgramIntent).where(ProgramIntent.program_id == p.id)).first(),
        researcher=researcher, llm=llm)

    assert result.revision.map_health == "solid but MoE is missing"
    assert len(result.changes) == 1  # the started-leg change was dropped
    assert result.changes[0].kind == "add_topic"
    assert result.changes[0].status == "proposed"
    kinds = [e.kind for e in result.events]
    assert "program_revision:plan" in kinds
    assert "program_revision:changes_dropped" in kinds
    assert all(e.program_id == p.id for e in result.events)


def test_run_revision_refuses_open_revision_and_zero_sources(session):
    p, m1, m2, l1, l2 = _program(session)
    intent = session.exec(
        select(ProgramIntent).where(ProgramIntent.program_id == p.id)).first()

    class EmptyResearcher:
        def search(self, brief):
            return []

    with pytest.raises(ValueError, match="no sources"):
        run_revision(session, p, intent, researcher=EmptyResearcher(),
                     llm=ScriptedLLMClient([]))
    assert session.exec(select(MapRevision)).all() == []  # nothing persisted

    # seed an open revision → second run refused
    rev = MapRevision(program_id=p.id)
    session.add(rev)
    session.commit()
    session.add(MapChange(revision_id=rev.id, kind="add_topic",
                          payload={"milestone_id": m2.id, "title": "X"}))
    session.commit()
    with pytest.raises(ValueError, match="open revision"):
        run_revision(session, p, intent,
                     researcher=ScriptedResearcherClient({}),
                     llm=ScriptedLLMClient([]))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_revision_pass.py -q`
Expected: FAIL with `ImportError: cannot import name 'REVISION_ANGLES'`

- [ ] **Step 4: Implement**

Append to `src/adaptive_academy/engine/revision.py` (extend the imports at top of file accordingly: `dataclass`/`field` from dataclasses, `fan_out_with_retry` from `adaptive_academy.engine.fanout`, `SearchBrief`, `ResearcherClient`, `RawSource` from `adaptive_academy.llm.researcher_types`, `structured_json` from `adaptive_academy.llm.structured`, `LLMClient` from `adaptive_academy.llm.types`, `PROGRAM_REVISION` from `adaptive_academy.prompts`, and `AgentEvent`, `MapChange`, `MapRevision`, `ProgramIntent` from `adaptive_academy.models`):

```python
# (angle_key, query_template) — {goal}/{focus}/{since} are filled in.
REVISION_ANGLES: list[tuple[str, str]] = [
    ("whats_new", "Important developments in {focus} since {since} relevant to {goal}"),
    ("curricula_check", "Changes since {since} in canonical curricula, courses, or qualifying-exam syllabi for {goal}"),
    ("frontier_shifts", "New architecture families, methods, or results since {since} that would change a 1-2 year study plan for {focus}"),
]


def build_revision_briefs(goal: str, focus: str, since_label: str) -> list[SearchBrief]:
    return [SearchBrief(angle=a, query=t.format(goal=goal, focus=focus or goal, since=since_label))
            for a, t in REVISION_ANGLES]


REVISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "map_health": {"type": "string"},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": [
                        "add_topic", "add_milestone", "revise_milestone",
                        "prune_topic", "prune_milestone"]},
                    "payload": {"type": "object"},
                    "why": {"type": "string"},
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["kind", "payload", "why"],
            },
        },
    },
    "required": ["map_health", "changes"],
}


def serialize_map(session: Session, program: Program) -> str:
    """The current map, with database ids and statuses, for the synthesis prompt.
    Archived milestones are excluded — they are not revisable surface."""
    lines = [f"PROGRAM: {program.title}"]
    milestones = session.exec(
        select(Milestone)
        .where(Milestone.program_id == program.id, Milestone.archived == False)  # noqa: E712
        .order_by(Milestone.order_index)
    ).all()
    for m in milestones:
        lines.append(f"milestone id={m.id} [gate: {m.gate_status}]: {m.title} — {m.success_criteria}")
        for link in session.exec(
            select(ProgramTopicLink).where(ProgramTopicLink.milestone_id == m.id)
        ).all():
            lines.append(f"  link id={link.id} ({link.status}): {link.proposed_title}")
    return "\n".join(lines)


def _milestone_untouchable(session: Session, m: Milestone) -> bool:
    """Started work or a passed gate makes a milestone immune to revise/prune."""
    if m.gate_status == "passed":
        return True
    started = session.exec(
        select(ProgramTopicLink).where(
            ProgramTopicLink.milestone_id == m.id,
            ProgramTopicLink.status == "started",
        )
    ).first()
    return started is not None


def validate_change(session: Session, program: Program, kind: str, payload: dict) -> str | None:
    """Shared parse-time AND apply-time gate. Returns a reason to drop/refuse, or None."""

    def _milestone(mid) -> Milestone | None:
        m = session.get(Milestone, mid) if isinstance(mid, int) else None
        return m if m is not None and m.program_id == program.id and not m.archived else None

    if kind == "add_topic":
        m = _milestone(payload.get("milestone_id"))
        if m is None:
            return "unresolvable milestone"
        title = str(payload.get("title", "")).strip()
        if not title:
            return "missing title"
        existing = session.exec(
            select(ProgramTopicLink).where(ProgramTopicLink.milestone_id == m.id)
        ).all()
        if any(link.status != "pruned"
               and link.proposed_title.strip().casefold() == title.casefold()
               for link in existing):
            return "duplicate topic title"
        return None
    if kind == "add_milestone":
        after = payload.get("after_milestone_id")
        if after is not None and _milestone(after) is None:
            return "unresolvable after_milestone_id"
        if not str(payload.get("title", "")).strip():
            return "missing title"
        return None
    if kind == "revise_milestone":
        m = _milestone(payload.get("milestone_id"))
        if m is None:
            return "unresolvable milestone"
        if _milestone_untouchable(session, m):
            return "milestone is started or passed"
        if payload.get("title") is None and payload.get("success_criteria") is None:
            return "no fields to revise"
        return None
    if kind == "prune_milestone":
        m = _milestone(payload.get("milestone_id"))
        if m is None:
            return "unresolvable milestone"
        if _milestone_untouchable(session, m):
            return "milestone is started or passed"
        return None
    if kind == "prune_topic":
        link_id = payload.get("link_id")
        link = session.get(ProgramTopicLink, link_id) if isinstance(link_id, int) else None
        if link is None:
            return "unresolvable link"
        m = session.get(Milestone, link.milestone_id)
        if m is None or m.program_id != program.id:
            return "unresolvable link"
        if link.status == "started":
            return "link is started"
        if link.status == "pruned":
            return "already pruned"
        return None
    return f"unknown kind {kind!r}"


@dataclass
class RevisionResult:
    revision: MapRevision
    changes: list[MapChange]
    events: list[AgentEvent]


def _since_label(session: Session, program: Program) -> str:
    latest = session.exec(
        select(MapRevision).where(MapRevision.program_id == program.id)
        .order_by(MapRevision.id.desc())
    ).first()
    dt = latest.created_at if latest else program.created_at
    return dt.strftime("%B %Y")


def run_revision(
    session: Session,
    program: Program,
    intent: ProgramIntent | None,
    *,
    researcher: ResearcherClient,
    llm: LLMClient,
    max_workers: int = 3,
) -> RevisionResult:
    """Fan out the freshness angles, synthesize a diff, persist it as proposals."""
    open_change = session.exec(
        select(MapChange)
        .join(MapRevision)
        .where(MapRevision.program_id == program.id, MapChange.status == "proposed")
    ).first()
    if open_change is not None:
        raise ValueError("program has an open revision; resolve it first")

    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(program_id=program.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    focus = intent.focus_area if intent else ""
    briefs = build_revision_briefs(program.goal_statement or program.title,
                                   focus, _since_label(session, program))
    emit("program_revision:plan", f"{len(briefs)} briefs")

    per_brief, failures, recovered = fan_out_with_retry(briefs, researcher, max_workers)
    raw: list[RawSource] = []
    for i, brief in enumerate(briefs):
        for s in per_brief[i]:
            s.angle = brief.angle
        if i in failures:
            emit("program_revision:subagent_error", f"{brief.angle}: {failures[i]}")
        elif i in recovered:
            emit("program_revision:subagent_retry",
                 f"{brief.angle}: recovered {recovered[i]} sources")
        else:
            emit("program_revision:subagent", f"{brief.angle}: {len(per_brief[i])} sources")
        raw.extend(per_brief[i])

    if briefs and not raw:
        session.commit()  # persist the trace so the failure is observable
        raise ValueError("revision research produced no sources; retry when connectivity is restored")

    emit("prompt", PROGRAM_REVISION.tag)
    user_msg = "\n\n".join([
        "<<<CURRENT MAP>>>", serialize_map(session, program),
        "<<<LEARNINGS DIGEST>>>", build_learnings_digest(session, program),
        "<<<SOURCES>>>",
        "\n".join(f"- [{s.angle}] {s.title} ({s.url}) — {s.summary}".rstrip(" —") for s in raw),
    ])
    data = structured_json(llm, PROGRAM_REVISION,
                           [{"role": "user", "content": user_msg}],
                           schema=REVISION_SCHEMA, tool_name="emit_revision")

    revision = MapRevision(program_id=program.id, map_health=str(data.get("map_health", "")))
    session.add(revision)
    session.flush()  # id without committing

    changes: list[MapChange] = []
    dropped = 0
    for ch in data.get("changes", []) or []:
        kind = str(ch.get("kind", ""))
        payload = ch.get("payload") if isinstance(ch.get("payload"), dict) else {}
        reason = validate_change(session, program, kind, payload)
        if reason is not None:
            dropped += 1
            continue
        change = MapChange(revision_id=revision.id, kind=kind, payload=payload,
                           why=str(ch.get("why", "")),
                           source_urls=list(ch.get("source_urls", []) or []))
        session.add(change)
        changes.append(change)
    if dropped:
        emit("program_revision:changes_dropped", f"{dropped} invalid change(s) discarded")
    emit("program_revision:done", f"{len(changes)} changes proposed")
    session.commit()
    session.refresh(revision)
    for c in changes:
        session.refresh(c)
    return RevisionResult(revision=revision, changes=changes, events=events)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_revision_pass.py tests/test_revision_digest.py -q` — Expected: all pass. Then full suite + ruff.

- [ ] **Step 6: Commit**

```bash
git add src/adaptive_academy/prompts.py src/adaptive_academy/engine/revision.py tests/test_revision_pass.py
git commit -m "feat(revision): 3-angle freshness pass, diff synthesis, code-enforced validation"
```

---

### Task 4: Gate-passed event + apply/reject engine

**Files:**
- Modify: `src/adaptive_academy/engine/gates.py` (emit on transition to passed)
- Modify: `src/adaptive_academy/engine/revision.py` (append apply/reject + nudge helper)
- Test: `tests/test_revision_apply.py`, extend `tests/test_gates_orchestrator.py`

**Interfaces:**
- Consumes: Tasks 1–3.
- Produces:
  - `gates.milestone_gate` emits `AgentEvent(program_id=..., kind="program:gate_passed", detail=f"milestone {m.id}")` exactly when `gate_status` transitions to `"passed"`.
  - `revision.apply_change(session, program: Program, change: MapChange) -> None` — re-validates via `validate_change`, raises `ValueError` on refusal or non-proposed status; applies + flips `status="accepted"` in one commit.
  - `revision.reject_change(session, change: MapChange) -> None` — flips `status="rejected"` (ValueError if not proposed).
  - `revision.revision_suggested(session, program: Program) -> bool` — a `program:gate_passed` event newer (by id) than the latest `MapRevision`, or any such event when no revision exists.

- [ ] **Step 1: Write the failing gate-event test** (append to `tests/test_gates_orchestrator.py`)

```python
def test_gate_pass_transition_emits_event_once(session):
    from adaptive_academy.models import AgentEvent
    from sqlmodel import select as _select

    m, lb = _seed_milestone(session)
    session.add(Assessment(concept_id=lb.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=lb.id, kind="recall", prompt="p", score=0.85,
                           created_at=T0 + timedelta(days=8)))
    session.commit()
    milestone_gate(session, m)  # open -> passed: emits
    milestone_gate(session, m)  # stays passed: must NOT emit again
    events = session.exec(_select(AgentEvent).where(
        AgentEvent.kind == "program:gate_passed")).all()
    assert len(events) == 1
    assert events[0].detail == f"milestone {m.id}"
    assert events[0].program_id is not None
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_gates_orchestrator.py -q`
Expected: the new test FAILS (`len(events) == 1` → 0 found); the existing 5 pass.

- [ ] **Step 3: Implement the emit**

In `src/adaptive_academy/engine/gates.py`, add `AgentEvent` to the models import, and change the sync block in `milestone_gate`:

```python
    if new_status != milestone.gate_status:
        if new_status == "passed":
            # Timestamped signal for the revision nudge (spec §4.4): emitted only
            # on the transition, never on a re-evaluation that stays passed.
            session.add(AgentEvent(program_id=milestone.program_id,
                                   kind="program:gate_passed",
                                   detail=f"milestone {milestone.id}"))
        milestone.gate_status = new_status
        session.add(milestone)
        session.commit()
        session.refresh(milestone)
```

Run: `uv run pytest tests/test_gates_orchestrator.py -q` — Expected: 6 passed.

- [ ] **Step 4: Write the failing apply/reject/nudge tests**

```python
# tests/test_revision_apply.py
import pytest
from sqlmodel import select

from adaptive_academy.engine.revision import (
    apply_change,
    reject_change,
    revision_suggested,
)
from adaptive_academy.models import (
    AgentEvent, MapChange, MapRevision, Milestone, Program, ProgramTopicLink,
)


def _program(session):
    p = Program(title="P", goal_statement="g")
    session.add(p)
    session.commit()
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0)
    m2 = Milestone(program_id=p.id, title="Architectures", order_index=1)
    session.add(m1); session.add(m2)
    session.commit()
    link = ProgramTopicLink(milestone_id=m2.id, proposed_title="Attention", status="stub")
    session.add(link)
    rev = MapRevision(program_id=p.id)
    session.add(rev)
    session.commit()
    return p, m1, m2, link, rev


def _change(session, rev, kind, payload):
    c = MapChange(revision_id=rev.id, kind=kind, payload=payload)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def test_apply_add_topic_creates_revision_stub(session):
    p, m1, m2, link, rev = _program(session)
    c = _change(session, rev, "add_topic", {"milestone_id": m2.id, "title": "MoE routing"})
    apply_change(session, p, c)
    assert c.status == "accepted"
    links = session.exec(select(ProgramTopicLink).where(
        ProgramTopicLink.milestone_id == m2.id)).all()
    new = [x for x in links if x.proposed_title == "MoE routing"]
    assert len(new) == 1
    assert new[0].status == "stub" and new[0].added_by == "revision"


def test_apply_add_milestone_slots_and_shifts(session):
    p, m1, m2, link, rev = _program(session)
    c = _change(session, rev, "add_milestone",
                {"after_milestone_id": m1.id, "title": "Math refresh",
                 "success_criteria": "derive it cold",
                 "topics": [{"title": "Jacobians", "why": "gap"}]})
    apply_change(session, p, c)
    ordered = session.exec(select(Milestone).where(Milestone.program_id == p.id)
                           .order_by(Milestone.order_index)).all()
    assert [m.title for m in ordered] == ["Foundations", "Math refresh", "Architectures"]
    assert [m.order_index for m in ordered] == [0, 1, 2]
    new_links = session.exec(select(ProgramTopicLink).where(
        ProgramTopicLink.milestone_id == ordered[1].id)).all()
    assert [(x.proposed_title, x.status, x.added_by) for x in new_links] == [
        ("Jacobians", "stub", "revision")]


def test_apply_prunes_and_revise(session):
    p, m1, m2, link, rev = _program(session)
    apply_change(session, p, _change(session, rev, "prune_topic", {"link_id": link.id}))
    session.refresh(link)
    assert link.status == "pruned"
    apply_change(session, p, _change(session, rev, "revise_milestone",
                                     {"milestone_id": m2.id, "success_criteria": "new bar"}))
    session.refresh(m2)
    assert m2.success_criteria == "new bar"
    apply_change(session, p, _change(session, rev, "prune_milestone", {"milestone_id": m2.id}))
    session.refresh(m2)
    assert m2.archived is True


def test_apply_revalidates_against_current_state(session):
    p, m1, m2, link, rev = _program(session)
    c = _change(session, rev, "prune_topic", {"link_id": link.id})
    link.status = "started"  # map changed between pass and accept
    session.add(link)
    session.commit()
    with pytest.raises(ValueError, match="started"):
        apply_change(session, p, c)
    session.refresh(c)
    assert c.status == "proposed"  # untouched on refusal


def test_reject_and_double_resolve_guards(session):
    p, m1, m2, link, rev = _program(session)
    c = _change(session, rev, "prune_topic", {"link_id": link.id})
    reject_change(session, c)
    assert c.status == "rejected"
    with pytest.raises(ValueError):
        apply_change(session, p, c)  # already resolved
    with pytest.raises(ValueError):
        reject_change(session, c)


def test_revision_suggested_truth_table(session):
    p = Program(title="P2", goal_statement="g")
    session.add(p)
    session.commit()
    # no events, no revisions -> False
    assert revision_suggested(session, p) is False
    # gate passed, no revision yet -> True
    session.add(AgentEvent(program_id=p.id, kind="program:gate_passed", detail="x"))
    session.commit()
    assert revision_suggested(session, p) is True
    # revision after the event -> False
    session.add(MapRevision(program_id=p.id))
    session.commit()
    assert revision_suggested(session, p) is False
    # a later gate pass -> True again
    session.add(AgentEvent(program_id=p.id, kind="program:gate_passed", detail="y"))
    session.commit()
    assert revision_suggested(session, p) is True
```

- [ ] **Step 5: Run to verify they fail**

Run: `uv run pytest tests/test_revision_apply.py -q`
Expected: FAIL with `ImportError: cannot import name 'apply_change'`

- [ ] **Step 6: Implement apply/reject/nudge**

Append to `src/adaptive_academy/engine/revision.py`:

```python
def apply_change(session: Session, program: Program, change: MapChange) -> None:
    """Apply an accepted change atomically. Re-validates against CURRENT state —
    the map may have moved between the revision pass and this accept."""
    if change.status != "proposed":
        raise ValueError(f"change already {change.status}")
    reason = validate_change(session, program, change.kind, change.payload)
    if reason is not None:
        raise ValueError(f"change no longer applies: {reason}")

    payload = change.payload
    if change.kind == "add_topic":
        session.add(ProgramTopicLink(
            milestone_id=payload["milestone_id"], status="stub",
            proposed_title=str(payload["title"]).strip(),
            why=change.why, sources=change.source_urls, added_by="revision"))
    elif change.kind == "add_milestone":
        after = payload.get("after_milestone_id")
        siblings = session.exec(
            select(Milestone).where(Milestone.program_id == program.id)
            .order_by(Milestone.order_index)
        ).all()
        new_index = 0
        if after is not None:
            after_m = session.get(Milestone, after)
            new_index = after_m.order_index + 1
        for s in siblings:
            if s.order_index >= new_index:
                s.order_index += 1
                session.add(s)
        m = Milestone(program_id=program.id, title=str(payload["title"]).strip(),
                      success_criteria=str(payload.get("success_criteria", "")),
                      order_index=new_index,
                      depends_on=[after] if after is not None else [])
        session.add(m)
        session.flush()
        for t in payload.get("topics", []) or []:
            if t.get("title"):
                session.add(ProgramTopicLink(
                    milestone_id=m.id, status="stub", proposed_title=str(t["title"]),
                    why=str(t.get("why", "")), added_by="revision"))
    elif change.kind == "revise_milestone":
        m = session.get(Milestone, payload["milestone_id"])
        if payload.get("title") is not None:
            m.title = str(payload["title"])
        if payload.get("success_criteria") is not None:
            m.success_criteria = str(payload["success_criteria"])
        session.add(m)
    elif change.kind == "prune_topic":
        link = session.get(ProgramTopicLink, payload["link_id"])
        link.status = "pruned"
        session.add(link)
    elif change.kind == "prune_milestone":
        m = session.get(Milestone, payload["milestone_id"])
        m.archived = True
        session.add(m)

    change.status = "accepted"
    session.add(change)
    session.commit()
    session.refresh(change)


def reject_change(session: Session, change: MapChange) -> None:
    if change.status != "proposed":
        raise ValueError(f"change already {change.status}")
    change.status = "rejected"
    session.add(change)
    session.commit()
    session.refresh(change)


def revision_suggested(session: Session, program: Program) -> bool:
    """True when a gate has passed since the map was last revised (spec §4.4)."""
    latest_pass = session.exec(
        select(AgentEvent).where(
            AgentEvent.program_id == program.id,
            AgentEvent.kind == "program:gate_passed",
        ).order_by(AgentEvent.id.desc())
    ).first()
    if latest_pass is None:
        return False
    latest_rev = session.exec(
        select(MapRevision).where(MapRevision.program_id == program.id)
        .order_by(MapRevision.id.desc())
    ).first()
    if latest_rev is None:
        return True
    return latest_pass.created_at > latest_rev.created_at
```

- [ ] **Step 7: Run to verify pass; full suite; commit**

Run: `uv run pytest tests/test_revision_apply.py tests/test_gates_orchestrator.py -q`, then `uv run pytest -q && uv run ruff check .`
Expected: all green, ruff clean.

```bash
git add src/adaptive_academy/engine/ tests/test_revision_apply.py tests/test_gates_orchestrator.py
git commit -m "feat(revision): gate-passed event, per-change apply with re-validation, nudge predicate"
```

---

### Task 5: API — revise/get/accept/reject, schema flags, archived-gate guard

**Files:**
- Modify: `src/adaptive_academy/api/schemas.py` (append revision schemas; extend `MilestoneOut`, `LinkOut`, `ProgramDetailOut`, `ProgramContextOut`)
- Modify: `src/adaptive_academy/api/routes_programs.py` (4 routes + helpers + archived guard)
- Modify: `src/adaptive_academy/api/routes_topics.py` (`program-context` gains `revision_suggested`)
- Test: `tests/test_api_revision.py`

**Interfaces:**
- Consumes: Tasks 1–4 (`run_revision`, `apply_change`, `reject_change`, `revision_suggested`).
- Produces (endpoints):
  - `POST /api/programs/{pid}/revise` → `MapRevisionOut` (400 on open revision / zero sources via ValueError; uses `get_researcher` + `get_llm`)
  - `GET /api/programs/{pid}/revision` → the open `MapRevisionOut` (404 when none open)
  - `POST /api/programs/{pid}/changes/{change_id}/accept` → `ProgramDetailOut` (fresh map; 404 cross-program, 400 on refusal/resolved)
  - `POST /api/programs/{pid}/changes/{change_id}/reject` → `ProgramDetailOut`
  - `GET .../milestones/{mid}/gate` → 400 "milestone archived" for archived milestones
  - Schema additions: `MapChangeOut{id, kind, payload: dict, why, source_urls, status}`, `MapRevisionOut{id, map_health, changes: list[MapChangeOut]}`; `MilestoneOut.archived: bool = False`; `LinkOut.added_by: str = "research"`; `ProgramDetailOut.revision_suggested: bool = False`, `ProgramDetailOut.has_open_revision: bool = False`; `ProgramContextOut.revision_suggested: bool = False`.

- [ ] **Step 1: Write the failing API tests**

```python
# tests/test_api_revision.py
import json

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Milestone, Program, ProgramIntent, ProgramTopicLink,
)


def _seed_program(session):
    p = Program(title="PhD prep", goal_statement="research-ready")
    session.add(p)
    session.commit()
    session.add(ProgramIntent(program_id=p.id, focus_area="custom LLMs"))
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0)
    m2 = Milestone(program_id=p.id, title="Architectures", order_index=1)
    session.add(m1); session.add(m2)
    session.commit()
    link = ProgramTopicLink(milestone_id=m2.id, proposed_title="Attention", status="stub")
    session.add(link)
    session.commit()
    return p, m1, m2, link


def _client(session: Session, synth: dict) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps(synth))])
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "whats_new": [RawSource(title="MoE", url="https://e.com/moe", tier=1)],
    })
    return TestClient(app)


def _synth(m2_id: int) -> dict:
    return {"map_health": "missing MoE",
            "changes": [{"kind": "add_topic",
                         "payload": {"milestone_id": m2_id, "title": "MoE routing"},
                         "why": "field moved", "source_urls": ["https://e.com/moe"]}]}


def test_revise_get_accept_flow(session):
    p, m1, m2, link = _seed_program(session)
    client = _client(session, _synth(m2.id))

    r = client.post(f"/api/programs/{p.id}/revise")
    assert r.status_code == 200
    body = r.json()
    assert body["map_health"] == "missing MoE"
    assert len(body["changes"]) == 1
    change_id = body["changes"][0]["id"]

    # open revision visible; detail flags set
    assert client.get(f"/api/programs/{p.id}/revision").json()["id"] == body["id"]
    detail = client.get(f"/api/programs/{p.id}").json()
    assert detail["has_open_revision"] is True

    # second revise refused while open
    assert client.post(f"/api/programs/{p.id}/revise").status_code == 400

    r = client.post(f"/api/programs/{p.id}/changes/{change_id}/accept")
    assert r.status_code == 200
    detail = r.json()
    assert detail["has_open_revision"] is False
    titles = [link["proposed_title"] for m in detail["milestones"] for link in m["links"]]
    assert "MoE routing" in titles
    added = [link for m in detail["milestones"] for link in m["links"]
             if link["proposed_title"] == "MoE routing"]
    assert added[0]["added_by"] == "revision"

    # revision now resolved -> GET 404, change re-resolve 400
    assert client.get(f"/api/programs/{p.id}/revision").status_code == 404
    assert client.post(f"/api/programs/{p.id}/changes/{change_id}/reject").status_code == 400


def test_reject_and_cross_program_guards(session):
    p, m1, m2, link = _seed_program(session)
    client = _client(session, _synth(m2.id))
    change_id = client.post(f"/api/programs/{p.id}/revise").json()["changes"][0]["id"]

    other = Program(title="Other", goal_statement="g")
    session.add(other)
    session.commit()
    assert client.post(f"/api/programs/{other.id}/changes/{change_id}/accept").status_code == 404

    r = client.post(f"/api/programs/{p.id}/changes/{change_id}/reject")
    assert r.status_code == 200
    assert r.json()["has_open_revision"] is False


def test_archived_milestone_gate_is_400(session):
    p, m1, m2, link = _seed_program(session)
    m2.archived = True
    session.add(m2)
    session.commit()
    client = _client(session, _synth(m2.id))
    r = client.get(f"/api/programs/{p.id}/milestones/{m2.id}/gate")
    assert r.status_code == 400
    assert "archived" in r.json()["detail"]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_api_revision.py -q`
Expected: FAIL (404s on the new routes).

- [ ] **Step 3: Implement schemas**

In `src/adaptive_academy/api/schemas.py`: add `archived: bool = False` to `MilestoneOut`; add `added_by: str = "research"` to `LinkOut`; add `revision_suggested: bool = False` and `has_open_revision: bool = False` to `ProgramDetailOut`; add `revision_suggested: bool = False` to `ProgramContextOut`; append:

```python
class MapChangeOut(BaseModel):
    id: int
    kind: str
    payload: dict = {}
    why: str = ""
    source_urls: list[str] = []
    status: str


class MapRevisionOut(BaseModel):
    id: int
    map_health: str
    changes: list[MapChangeOut]
```

- [ ] **Step 4: Implement routes**

In `src/adaptive_academy/api/routes_programs.py`: extend imports (`MapChange`, `MapRevision` from models; `MapChangeOut`, `MapRevisionOut` from schemas; `apply_change, reject_change, revision_suggested, run_revision` from `adaptive_academy.engine.revision`; `ProgramIntent` already imported). Update `_milestone_out` to pass `archived=m.archived`, `_link_out` to pass `added_by=link.added_by`. Update `_detail` to compute the two flags:

```python
def _open_revision(session: Session, program_id: int) -> MapRevision | None:
    change = session.exec(
        select(MapChange).join(MapRevision).where(
            MapRevision.program_id == program_id, MapChange.status == "proposed")
    ).first()
    return session.get(MapRevision, change.revision_id) if change else None


def _detail(session: Session, p: Program) -> ProgramDetailOut:
    milestones = session.exec(
        select(Milestone).where(Milestone.program_id == p.id).order_by(Milestone.order_index)
    ).all()
    return ProgramDetailOut(
        program=_program_out(session, p),
        milestones=[_milestone_out(session, m) for m in milestones],
        revision_suggested=revision_suggested(session, p),
        has_open_revision=_open_revision(session, p.id) is not None,
    )
```

Add the archived guard at the top of `get_gate` (after `_milestone_or_404`):

```python
    if m.archived:
        raise HTTPException(400, "milestone archived")
```

Append the routes:

```python
def _revision_out(session: Session, rev: MapRevision) -> MapRevisionOut:
    changes = session.exec(
        select(MapChange).where(MapChange.revision_id == rev.id).order_by(MapChange.id)
    ).all()
    return MapRevisionOut(
        id=rev.id, map_health=rev.map_health,
        changes=[MapChangeOut(id=c.id, kind=c.kind, payload=c.payload, why=c.why,
                              source_urls=c.source_urls, status=c.status)
                 for c in changes])


@router.post("/{program_id}/revise", response_model=MapRevisionOut)
def revise_map(
    program_id: int,
    session: Session = Depends(get_session),
    researcher: ResearcherClient = Depends(get_researcher),
    llm: LLMClient = Depends(get_llm),
):
    program = _program_or_404(session, program_id)
    intent = session.exec(
        select(ProgramIntent).where(ProgramIntent.program_id == program_id)
    ).first()
    try:
        result = run_revision(session, program, intent, researcher=researcher, llm=llm)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _revision_out(session, result.revision)


@router.get("/{program_id}/revision", response_model=MapRevisionOut)
def get_open_revision(program_id: int, session: Session = Depends(get_session)):
    _program_or_404(session, program_id)
    rev = _open_revision(session, program_id)
    if rev is None:
        raise HTTPException(404, "no open revision")
    return _revision_out(session, rev)


def _change_or_404(session: Session, program_id: int, change_id: int) -> MapChange:
    change = session.get(MapChange, change_id)
    if change is None:
        raise HTTPException(404, "change not found")
    rev = session.get(MapRevision, change.revision_id)
    if rev is None or rev.program_id != program_id:
        raise HTTPException(404, "change not found")
    return change


@router.post("/{program_id}/changes/{change_id}/accept", response_model=ProgramDetailOut)
def accept_change(
    program_id: int, change_id: int, session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    change = _change_or_404(session, program_id, change_id)
    try:
        apply_change(session, program, change)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    session.add(AgentEvent(program_id=program_id, kind="program:change_accepted",
                           detail=f"{change.kind} (change {change.id})"))
    session.commit()
    return _detail(session, program)


@router.post("/{program_id}/changes/{change_id}/reject", response_model=ProgramDetailOut)
def reject_change_route(
    program_id: int, change_id: int, session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    change = _change_or_404(session, program_id, change_id)
    try:
        reject_change(session, change)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _detail(session, program)
```

In `src/adaptive_academy/api/routes_topics.py` `get_program_context`: import `revision_suggested` from `adaptive_academy.engine.revision` and pass `revision_suggested=revision_suggested(session, program)` into `ProgramContextOut`.

- [ ] **Step 5: Run to verify pass; full suite; commit**

Run: `uv run pytest tests/test_api_revision.py -q`, then `uv run pytest -q && uv run ruff check .`
Expected: all green (existing program API tests must still pass with the new default-False schema fields).

```bash
git add src/adaptive_academy/api/ tests/test_api_revision.py
git commit -m "feat(revision): revise/get/accept/reject API, detail flags, archived-gate guard"
```

---

### Task 6: Frontend — revision panel, banners, archived toggle

**Files:**
- Modify: `frontend/src/lib/types.ts` (revision types; extend `MilestoneInfo`, `LinkInfo`, `ProgramDetail`, `ProgramContext`)
- Modify: `frontend/src/lib/api.ts` (4 calls)
- Modify: `frontend/src/routes/programs/[id]/+page.svelte` (panel, banner, button, archived toggle, provenance chip)
- Modify: `frontend/src/routes/topics/[id]/today/+page.svelte` (nudge line in the program strip)
- Test: `frontend/src/lib/programs.test.ts` (+ helper in `programs.ts`)

**Interfaces:**
- Consumes: Task 5 endpoints and schema fields.
- Produces: `api.reviseMap(id)`, `api.getOpenRevision(id)` (null on 404), `api.acceptChange(pid, changeId)`, `api.rejectChange(pid, changeId)`; types `MapChange`, `MapRevisionInfo`; helper `changeSummary(change) -> string` (human rendering of a change payload, unit-tested).

- [ ] **Step 1: Write the failing helper test** (append to `frontend/src/lib/programs.test.ts`)

```typescript
import { changeSummary } from './programs';

describe('changeSummary', () => {
  it('renders each change kind as a human sentence', () => {
    expect(changeSummary({ kind: 'add_topic', payload: { milestone_id: 2, title: 'MoE routing' } }))
      .toBe('Add topic “MoE routing”');
    expect(changeSummary({ kind: 'add_milestone', payload: { title: 'Math refresh' } }))
      .toBe('Add milestone “Math refresh”');
    expect(changeSummary({ kind: 'revise_milestone', payload: { milestone_id: 2, title: 'New title' } }))
      .toBe('Revise milestone: New title');
    expect(changeSummary({ kind: 'revise_milestone', payload: { milestone_id: 2, success_criteria: 'bar' } }))
      .toBe('Revise milestone: new success criteria');
    expect(changeSummary({ kind: 'prune_topic', payload: { link_id: 5 } }))
      .toBe('Prune a planned topic');
    expect(changeSummary({ kind: 'prune_milestone', payload: { milestone_id: 3 } }))
      .toBe('Archive a milestone');
    expect(changeSummary({ kind: 'mystery', payload: {} })).toBe('mystery');
  });
});
```

Run: `cd frontend && npx vitest run src/lib/programs.test.ts` — Expected: FAIL (no export).

- [ ] **Step 2: Implement the helper** (append to `frontend/src/lib/programs.ts`)

```typescript
export function changeSummary(change: { kind: string; payload: Record<string, unknown> }): string {
  const p = change.payload;
  switch (change.kind) {
    case 'add_topic':
      return `Add topic “${p.title}”`;
    case 'add_milestone':
      return `Add milestone “${p.title}”`;
    case 'revise_milestone':
      return p.title ? `Revise milestone: ${p.title}` : 'Revise milestone: new success criteria';
    case 'prune_topic':
      return 'Prune a planned topic';
    case 'prune_milestone':
      return 'Archive a milestone';
    default:
      return change.kind;
  }
}
```

Run: `npx vitest run src/lib/programs.test.ts` — Expected: PASS.

- [ ] **Step 3: Types + api calls**

Append to `frontend/src/lib/types.ts` (and extend: `MilestoneInfo` gains `archived: boolean`; `LinkInfo` gains `added_by: string`; `ProgramDetail` gains `revision_suggested: boolean; has_open_revision: boolean`; `ProgramContext` gains `revision_suggested: boolean`):

```typescript
export interface MapChange {
  id: number; kind: string; payload: Record<string, unknown>;
  why: string; source_urls: string[]; status: string;
}
export interface MapRevisionInfo { id: number; map_health: string; changes: MapChange[]; }
```

Append inside the `api` object in `frontend/src/lib/api.ts` (add `MapRevisionInfo` to the type-import line):

```typescript
  reviseMap: (id: number) =>
    fetch(`/api/programs/${id}/revise`, { method: 'POST' }).then(j<MapRevisionInfo>),
  getOpenRevision: (id: number) =>
    fetch(`/api/programs/${id}/revision`).then((r) =>
      r.status === 404 ? null : j<MapRevisionInfo>(r)
    ),
  acceptChange: (pid: number, changeId: number) =>
    fetch(`/api/programs/${pid}/changes/${changeId}/accept`, { method: 'POST' }).then(j<ProgramDetail>),
  rejectChange: (pid: number, changeId: number) =>
    fetch(`/api/programs/${pid}/changes/${changeId}/reject`, { method: 'POST' }).then(j<ProgramDetail>),
```

- [ ] **Step 4: Program map page**

In `frontend/src/routes/programs/[id]/+page.svelte` (match the page's existing idioms — runes, try/catch/finally with `busy`, `text-danger` errors, `Card`/`Button`/`Badge` from `$lib/ui`):

1. State: `let revision = $state<MapRevisionInfo | null>(null);` and `let showArchived = $state(false);`
2. In `load()`: after fetching detail, `revision = detail?.has_open_revision ? await api.getOpenRevision(programId).catch(() => null) : null;`
3. Header actions: a "Revise map" `Button` — `disabled={busy || detail?.has_open_revision}` — calling:

```typescript
  async function revise() {
    busy = true; error = '';
    try {
      revision = await api.reviseMap(programId);
      await load();
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
    busy = false;
  }
```

4. Banner (above the milestone rail, only when NOT in proposal-review mode):

```svelte
  {#if detail?.revision_suggested && !detail?.has_open_revision}
    <Card>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <p class="text-sm text-muted">Leg verified — revise the map with what you've learned?</p>
        <Button onclick={revise} disabled={busy}>Revise map</Button>
      </div>
    </Card>
  {/if}
```

5. Revision panel (when `revision` is non-null), rendered above the milestone rail:

```svelte
  {#if revision}
    <Card>
      <div class="eyebrow mb-2">Map revision</div>
      <p class="mb-4 text-sm text-muted">{revision.map_health}</p>
      <ul class="grid gap-3">
        {#each revision.changes.filter((c) => c.status === 'proposed') as c (c.id)}
          <li class="flex flex-wrap items-start justify-between gap-3 text-sm">
            <div class="min-w-0">
              <div class="text-fg">{changeSummary(c)}</div>
              <p class="mt-1 text-muted">{c.why}</p>
              {#if c.source_urls.length > 0}
                <p class="mt-1 truncate text-xs text-muted">
                  {#each c.source_urls.slice(0, 2) as u (u)}
                    <a class="text-accent hover:underline" href={u} target="_blank" rel="noreferrer">{u}</a>&nbsp;
                  {/each}
                </p>
              {/if}
            </div>
            <div class="flex shrink-0 gap-2">
              <Button onclick={() => resolveChange(c.id, true)} disabled={busy}>Accept</Button>
              <button class="text-sm text-muted hover:text-fg"
                      onclick={() => resolveChange(c.id, false)} disabled={busy}>Reject</button>
            </div>
          </li>
        {/each}
      </ul>
    </Card>
  {/if}
```

with:

```typescript
  async function resolveChange(changeId: number, accept: boolean) {
    busy = true; error = '';
    try {
      detail = accept
        ? await api.acceptChange(programId, changeId)
        : await api.rejectChange(programId, changeId);
      revision = detail.has_open_revision
        ? await api.getOpenRevision(programId).catch(() => null)
        : null;
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
    busy = false;
  }
```

6. Archived toggle: filter the milestone rail with `detail.milestones.filter((m) => showArchived || !m.archived)`; below the rail render a small `<button class="text-xs text-muted hover:text-fg" onclick={() => (showArchived = !showArchived)}>` showing "Show N archived" / "Hide archived" only when any milestone is archived; archived cards get reduced opacity (`opacity-60`) and an "Archived" `Badge`.
7. Provenance chip: in the link row, after the title: `{#if l.added_by === 'revision'}<Badge tone="accent">revision</Badge>{/if}` (`accent` exists in Badge's tone union).

- [ ] **Step 5: Today strip nudge**

In `frontend/src/routes/topics/[id]/today/+page.svelte`, inside the existing `{#if programCtx}` strip Card, after the unverified-concepts paragraph:

```svelte
      {#if programCtx.revision_suggested}
        <p class="mt-2 text-sm text-muted">
          Leg verified —
          <a class="text-accent hover:underline" href={`/programs/${programCtx.program_id}`}>
            revise the map</a> with what you've learned?
        </p>
      {/if}
```

- [ ] **Step 6: Verify + commit**

Run: `cd frontend && npx vitest run && npx svelte-check && npm run build`
Expected: vitest green; svelte-check ≤ 22 errors, none in touched files; build OK.

```bash
git add frontend/src/
git commit -m "feat(revision): revision panel, nudge banners, archived toggle, provenance chips"
```

---

### Task 7: Integration test + full verification

**Files:**
- Test: `tests/test_integration_revision_loop.py`

**Interfaces:**
- Consumes: everything above, via the HTTP API with scripted doubles.

- [ ] **Step 1: Write the integration test**

```python
# tests/test_integration_revision_loop.py
"""End-to-end revision loop (spec §7): seed a program with one passed leg →
revise (scripted researcher + LLM) → accept an add_topic and a prune_topic,
reject a revise_milestone → the map reflects exactly the accepted changes and
the nudge clears."""
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.engine.gates import milestone_gate
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, KnowledgeEstimate, Milestone, Program, ProgramIntent,
    ProgramTopicLink, Topic, Track,
)

T0 = datetime(2026, 7, 1)


def _seed(session):
    """Program with leg1 (started topic, verified evidence → passes) + leg2 (stubs)."""
    p = Program(title="PhD prep", goal_statement="research-ready")
    session.add(p)
    session.commit()
    session.add(ProgramIntent(program_id=p.id, focus_area="custom LLMs"))
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0)
    m2 = Milestone(program_id=p.id, title="Architectures", order_index=1)
    session.add(m1); session.add(m2)
    topic = Topic(title="Backprop")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Backprop")
    session.add(track)
    session.commit()
    c = Concept(track_id=track.id, name="Chain rule", is_load_bearing=True)
    session.add(c)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=c.id))
    session.add(Assessment(concept_id=c.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=c.id, kind="recall", prompt="p", score=0.85,
                           created_at=T0 + timedelta(days=8)))
    session.add(ProgramTopicLink(milestone_id=m1.id, topic_id=topic.id, status="started"))
    stub = ProgramTopicLink(milestone_id=m2.id, proposed_title="Old attention survey",
                            status="stub")
    session.add(stub)
    session.commit()
    milestone_gate(session, m1)  # flips to passed, emits program:gate_passed
    return p, m1, m2, stub


def _client(session: Session, synth: dict) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps(synth))])
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "whats_new": [RawSource(title="MoE", url="https://e.com/moe", tier=1,
                                summary="mixture of experts everywhere")],
        "frontier_shifts": [RawSource(title="SSMs", url="https://e.com/ssm", tier=1)],
    })
    return TestClient(app)


def test_revision_loop_end_to_end(session):
    p, m1, m2, stub = _seed(session)
    synth = {"map_health": "leg 2 predates the MoE/SSM shift",
             "changes": [
                 {"kind": "add_topic",
                  "payload": {"milestone_id": m2.id, "title": "MoE routing"},
                  "why": "field moved", "source_urls": ["https://e.com/moe"]},
                 {"kind": "prune_topic", "payload": {"link_id": stub.id},
                  "why": "superseded", "source_urls": []},
                 {"kind": "revise_milestone",
                  "payload": {"milestone_id": m2.id, "title": "Architectures v2"},
                  "why": "broaden", "source_urls": []},
             ]}
    client = _client(session, synth)

    # nudge is on (gate passed, never revised)
    assert client.get(f"/api/programs/{p.id}").json()["revision_suggested"] is True

    rev = client.post(f"/api/programs/{p.id}/revise").json()
    assert len(rev["changes"]) == 3  # all valid (m2 unstarted, stub prunable)
    by_kind = {c["kind"]: c["id"] for c in rev["changes"]}

    client.post(f"/api/programs/{p.id}/changes/{by_kind['add_topic']}/accept")
    client.post(f"/api/programs/{p.id}/changes/{by_kind['prune_topic']}/accept")
    detail = client.post(
        f"/api/programs/{p.id}/changes/{by_kind['revise_milestone']}/reject").json()

    # map reflects exactly the accepted changes
    leg2 = next(m for m in detail["milestones"] if m["id"] == m2.id)
    assert leg2["title"] == "Architectures"  # reject left it alone
    links = {link["proposed_title"]: link for link in leg2["links"]}
    assert links["MoE routing"]["status"] == "stub"
    assert links["MoE routing"]["added_by"] == "revision"
    assert links["Old attention survey"]["status"] == "pruned"

    # revision resolved; nudge cleared (revision postdates the gate pass)
    assert detail["has_open_revision"] is False
    assert detail["revision_suggested"] is False
    # trace exists
    kinds = [e["kind"] for e in client.get(f"/api/programs/{p.id}/events").json()]
    assert "program_revision:done" in kinds
    assert "program:gate_passed" in kinds
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_integration_revision_loop.py -q`
Expected: 1 passed. Debug notes: (a) `milestone_gate` in `_seed` must run BEFORE the client is built so the event exists; (b) the scripted LLM has exactly ONE payload — the revise call is the only LLM call in this loop; (c) `curricula_check` returning no sources is fine (angle succeeds with []).

- [ ] **Step 3: Full verification**

```bash
uv run pytest -q && uv run ruff check .
cd frontend && npx vitest run && npx svelte-check && npm run build && cd ..
uv run alembic upgrade head
```

Expected: all green/clean; svelte-check ≤ 22 pre-existing errors.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_revision_loop.py
git commit -m "test(revision): end-to-end revision loop — nudge→revise→accept/reject→map diff"
```

---

## Post-plan checklist (for the finishing session)

- Run superpowers:verification-before-completion before claiming done.
- Rebuild the container after merge (`docker compose up -d --build`) — the stale-build gotcha; the entrypoint auto-runs the new migration against the volume db.
- Live dogfood note: `POST /api/programs/1/revise` on the real program is a 3-angle web-search pass (cheaper than initial research); the map_health paragraph alone is worth reading.
- Backlog items NOT in this plan: program-delete endpoint; revision history UI; add_milestone rich depends_on edges (spec §9).
