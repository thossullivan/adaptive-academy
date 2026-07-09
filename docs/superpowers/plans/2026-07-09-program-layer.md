# Program Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Program layer above Topics — researched long-horizon programs with milestone gates computed from delayed + artifact evidence, lazy topic materialization, and cross-topic knowledge carryover.

**Architecture:** Five new additive SQLModel tables (`Program`, `ProgramIntent`, `Milestone`, `ProgramTopicLink`, `ConceptAlias`) plus a nullable `AgentEvent.program_id` column. A program-level research fan-out reuses the `ResearcherClient` seam and `ThreadPoolExecutor` muscle from `engine/research.py`; gate verdicts are pure functions over existing `Assessment` rows in a new `engine/gates.py` (no LLM); alias carryover is a post-pass hook after curriculum generation. New FastAPI router `routes_programs.py`; SvelteKit pages `/programs`, `/programs/new`, `/programs/[id]`; a program strip on the per-topic Today page.

**Tech Stack:** Python/FastAPI/SQLModel/SQLite + Alembic, SvelteKit/Tailwind, existing `structured_json` LLM seam, pytest + vitest.

**Spec:** `docs/superpowers/specs/2026-07-09-program-layer.md`. Deviations from spec (all cosmetic, decided here): gate route is `GET /api/programs/{pid}/milestones/{mid}/gate` (more RESTful than the spec's `/gate/{milestone_id}`); `ProgramTopicLink.status` uses `proposed|pruned|stub|started` (`pruned` added for review parity with SourceDoc; `done` dropped as YAGNI); the topic breadcrumb ships on the Today strip and Track page header.

## Global Constraints

- All schema changes are **additive**; existing tables keep their meaning (spec §2.1).
- Gate verdicts are **pure functions over existing evidence rows** — no LLM calls (spec §2.6).
- Gate thresholds: artifact score ≥ **0.7**, recall delay ≥ **7 days**, held ratio **0.85** (constants in `engine/gates.py`; spec §4.2/§10 — tunable defaults).
- Gates **nag, never block** — override requires a logged reason; progression is never prevented (spec §2.5).
- Fan-out resilience: one failing angle must not abort research (`program_research:subagent_error` event; spec §7).
- Every new prompt lives in `adaptive_academy/prompts.py` as a version-tagged `Prompt`; its `.tag` is emitted as an `AgentEvent(kind="prompt")` before the LLM call.
- SQLite round-trips datetimes tz-naive — compare with the `_naive_utc` pattern from `engine/decay.py`.
- Run backend tests with `uv run pytest -q`, lint with `uv run ruff check .`, frontend checks with `cd frontend && npx svelte-check && npm run build && npx vitest run`.
- Commit after every task (at minimum); messages follow the repo's `feat:`/`fix:`/`docs:` style.

---

### Task 1: Models + migration

**Files:**
- Modify: `src/adaptive_academy/models.py` (append new tables; add `program_id` to `AgentEvent`)
- Create: `alembic/versions/<generated>_program_layer_tables.py`
- Test: `tests/test_program_models.py`

**Interfaces:**
- Produces: `Program(id, title, goal_statement, status, created_at, updated_at)`, `ProgramIntent(id, program_id, target_depth, prior_knowledge, weekly_time_budget, horizon, focus_area)`, `Milestone(id, program_id, title, success_criteria, order_index, gate_status, depends_on, override_reason)`, `ProgramTopicLink(id, milestone_id, topic_id, status, proposed_title, why, sources, created_at)`, `ConceptAlias(id, program_id, canonical_name, concept_id, created_at)`, `AgentEvent.program_id: Optional[int]`. All later tasks import these from `adaptive_academy.models`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_program_models.py
from adaptive_academy.models import (
    AgentEvent,
    Concept,
    ConceptAlias,
    Milestone,
    Program,
    ProgramIntent,
    ProgramTopicLink,
    Topic,
    Track,
)


def test_program_tables_roundtrip(session):
    program = Program(title="PhD-level CS: custom LLMs", goal_statement="research-ready depth")
    session.add(program)
    session.commit()
    session.refresh(program)
    assert program.status == "active"
    assert program.created_at is not None

    session.add(ProgramIntent(program_id=program.id, target_depth="phd",
                              weekly_time_budget="10h", horizon="2 years",
                              focus_area="custom LLM models"))
    m1 = Milestone(program_id=program.id, title="Math foundations",
                   success_criteria="derive backprop cold", order_index=0)
    session.add(m1)
    session.commit()
    session.refresh(m1)
    assert m1.gate_status == "open"
    assert m1.depends_on == []

    m2 = Milestone(program_id=program.id, title="Architectures", order_index=1,
                   depends_on=[m1.id])
    session.add(m2)
    session.commit()
    session.refresh(m2)
    assert m2.depends_on == [m1.id]

    link = ProgramTopicLink(milestone_id=m1.id, proposed_title="Linear algebra for DL",
                            why="prereq", sources=["https://example.com/syllabus"])
    session.add(link)
    session.commit()
    session.refresh(link)
    assert link.status == "proposed"
    assert link.topic_id is None  # proposed candidates have no Topic yet


def test_concept_alias_and_program_event(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="T")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="Attention")
    session.add(concept)
    program = Program(title="P", goal_statement="g")
    session.add(program)
    session.commit()

    session.add(ConceptAlias(program_id=program.id, canonical_name="attention",
                             concept_id=concept.id))
    session.add(AgentEvent(program_id=program.id, kind="program_research:plan", detail="5 briefs"))
    session.commit()

    ev = session.query(AgentEvent).filter(AgentEvent.program_id == program.id).one()
    assert ev.kind == "program_research:plan"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_program_models.py -q`
Expected: FAIL with `ImportError: cannot import name 'Program'`

- [ ] **Step 3: Implement the models**

In `src/adaptive_academy/models.py`, change `AgentEvent` (docstring + one field):

```python
class AgentEvent(SQLModel, table=True):
    """Observability trace: one row per engine/agent step.

    Exactly one of conversation_id / topic_id / program_id is set (app-level invariant).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id")
    topic_id: Optional[int] = Field(default=None, foreign_key="topic.id")
    program_id: Optional[int] = Field(default=None, foreign_key="program.id")
    kind: str
    detail: str = ""
    created_at: datetime = Field(default_factory=_now)
```

Append at the end of `models.py`:

```python
class Program(SQLModel, table=True):
    """A long-horizon learning program (spec 2026-07-09-program-layer §3)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    goal_statement: str = ""
    status: str = "active"  # active | paused | done
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class ProgramIntent(SQLModel, table=True):
    """Structured intake for the program-level research pass (mirrors TopicIntent)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    program_id: int = Field(foreign_key="program.id", unique=True)
    target_depth: str = ""
    prior_knowledge: str = ""
    weekly_time_budget: str = ""
    horizon: str = ""
    focus_area: str = ""
    created_at: datetime = Field(default_factory=_now)


class Milestone(SQLModel, table=True):
    """An ordered stage of a Program; the unit gates attach to."""

    id: Optional[int] = Field(default=None, primary_key=True)
    program_id: int = Field(foreign_key="program.id")
    title: str
    success_criteria: str = ""
    order_index: int = 0
    gate_status: str = "open"  # open | passed | overridden
    depends_on: list[int] = Field(default_factory=list, sa_column=Column(JSON))
    override_reason: str = ""
    created_at: datetime = Field(default_factory=_now)


class ProgramTopicLink(SQLModel, table=True):
    """A Milestone's topic slot: proposed by research, stubbed on accept, started on demand."""

    id: Optional[int] = Field(default=None, primary_key=True)
    milestone_id: int = Field(foreign_key="milestone.id")
    topic_id: Optional[int] = Field(default=None, foreign_key="topic.id")
    status: str = "proposed"  # proposed | pruned | stub | started
    proposed_title: str = ""
    why: str = ""
    sources: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class ConceptAlias(SQLModel, table=True):
    """Cross-topic concept identity inside a Program (knowledge carryover, spec §4.4)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    program_id: int = Field(foreign_key="program.id")
    canonical_name: str
    concept_id: int = Field(foreign_key="concept.id", unique=True)
    created_at: datetime = Field(default_factory=_now)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_program_models.py -q`
Expected: 2 passed

- [ ] **Step 5: Create the migration**

Run: `uv run alembic revision -m "program layer tables"` and fill the generated file (keep the generated `revision` id; `down_revision` must be `"58d8eefb9417"`):

```python
"""program layer tables

Revision ID: <generated>
Revises: 58d8eefb9417
Create Date: 2026-07-09
"""
from alembic import op
import sqlalchemy as sa

revision = "<generated>"
down_revision = "58d8eefb9417"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "program",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("goal_statement", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "programintent",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=False, unique=True),
        sa.Column("target_depth", sa.String(), nullable=False, server_default=""),
        sa.Column("prior_knowledge", sa.String(), nullable=False, server_default=""),
        sa.Column("weekly_time_budget", sa.String(), nullable=False, server_default=""),
        sa.Column("horizon", sa.String(), nullable=False, server_default=""),
        sa.Column("focus_area", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "milestone",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("success_criteria", sa.String(), nullable=False, server_default=""),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gate_status", sa.String(), nullable=False, server_default="open"),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("override_reason", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "programtopiclink",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("milestone_id", sa.Integer(), sa.ForeignKey("milestone.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topic.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        sa.Column("proposed_title", sa.String(), nullable=False, server_default=""),
        sa.Column("why", sa.String(), nullable=False, server_default=""),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "conceptalias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("concept_id", sa.Integer(), sa.ForeignKey("concept.id"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.add_column("agentevent",
                  sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=True))


def downgrade() -> None:
    op.drop_column("agentevent", "program_id")
    op.drop_table("conceptalias")
    op.drop_table("programtopiclink")
    op.drop_table("milestone")
    op.drop_table("programintent")
    op.drop_table("program")
```

- [ ] **Step 6: Verify migration round-trips**

Run (against a scratch copy so the live db is untouched):

```bash
cd /Users/tomsullivan/Projects/adaptive-academy
cp adaptive_academy.db /tmp/aa-mig-test.db 2>/dev/null || true
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```

Expected: all three commands exit 0. Then `uv run pytest -q` — full suite green.

- [ ] **Step 7: Commit**

```bash
git add src/adaptive_academy/models.py alembic/versions/*program_layer* tests/test_program_models.py
git commit -m "feat(program): Program/ProgramIntent/Milestone/ProgramTopicLink/ConceptAlias tables + AgentEvent.program_id"
```

---

### Task 2: Gate evidence engine (`engine/gates.py`)

**Files:**
- Create: `src/adaptive_academy/engine/gates.py`
- Test: `tests/test_gates_pure.py`, `tests/test_gates_orchestrator.py`

**Interfaces:**
- Consumes: `Assessment`, `Concept`, `Milestone`, `ProgramTopicLink`, `Track` from Task 1 / existing models.
- Produces:
  - `ConceptEvidence(concept_id: int, name: str, delayed_ok: bool, artifact_ok: bool, verdict: str)` — verdict ∈ `verified | stale | weak_artifact | never_probed_cold`
  - `GateReport(milestone_id: int, verdict: str, reason: str, concepts: list[ConceptEvidence])` — verdict ∈ `passed | open | overridden`
  - `evaluate_concept(concept_id: int, name: str, assessments: list[Assessment]) -> ConceptEvidence` (pure)
  - `milestone_gate(session: Session, milestone: Milestone) -> GateReport` (orchestrator; syncs `milestone.gate_status`)
  - Constants: `DELAY_DAYS = 7`, `HELD_RATIO = 0.85`, `ARTIFACT_THRESHOLD = 0.7`, `ARTIFACT_KINDS = {"artifact_review", "teach", "productive_failure"}`

- [ ] **Step 1: Write the failing pure-logic tests**

```python
# tests/test_gates_pure.py
from datetime import datetime, timedelta

from adaptive_academy.engine.gates import evaluate_concept
from adaptive_academy.models import Assessment

T0 = datetime(2026, 7, 1, 12, 0, 0)


def _a(id: int, kind: str, score: float, days_after_t0: float) -> Assessment:
    return Assessment(id=id, concept_id=1, kind=kind, prompt="p", score=score,
                      created_at=T0 + timedelta(days=days_after_t0))


def test_no_assessments_is_never_probed_cold():
    ev = evaluate_concept(1, "attention", [])
    assert ev.verdict == "never_probed_cold"
    assert not ev.delayed_ok and not ev.artifact_ok


def test_recall_too_soon_does_not_count_as_delayed():
    rows = [_a(1, "self_explanation", 0.8, 0),
            _a(2, "recall", 0.8, 3)]  # only 3 days later
    assert evaluate_concept(1, "attention", rows).verdict == "never_probed_cold"


def test_delayed_held_recall_but_no_artifact_is_weak_artifact():
    rows = [_a(1, "self_explanation", 0.8, 0),
            _a(2, "recall", 0.75, 8)]  # 8d later, 0.75 >= 0.8*0.85
    ev = evaluate_concept(1, "attention", rows)
    assert ev.delayed_ok and not ev.artifact_ok
    assert ev.verdict == "weak_artifact"


def test_delayed_decayed_recall_is_stale():
    rows = [_a(1, "self_explanation", 0.9, 0),
            _a(2, "recall", 0.5, 8)]  # 0.5 < 0.9*0.85
    assert evaluate_concept(1, "attention", rows).verdict == "stale"


def test_latest_delayed_recall_wins_over_earlier_held():
    rows = [_a(1, "teach", 0.9, 0),
            _a(2, "recall", 0.9, 8),    # held
            _a(3, "self_explanation", 0.9, 9),
            _a(4, "recall", 0.3, 20)]   # latest delayed recall decayed
    assert evaluate_concept(1, "attention", rows).verdict == "stale"


def test_verified_needs_delayed_held_plus_artifact_at_threshold():
    rows = [_a(1, "teach", 0.7, 0),          # artifact at threshold counts
            _a(2, "recall", 0.65, 8)]        # 0.65 >= 0.7*0.85 = 0.595
    ev = evaluate_concept(1, "attention", rows)
    assert ev.delayed_ok and ev.artifact_ok
    assert ev.verdict == "verified"


def test_weak_artifact_score_below_threshold():
    rows = [_a(1, "productive_failure", 0.69, 0),
            _a(2, "recall", 0.69, 8)]
    assert evaluate_concept(1, "attention", rows).verdict == "weak_artifact"


def test_recall_with_no_prior_non_recall_is_ignored():
    rows = [_a(1, "recall", 0.9, 0)]  # nothing to be "delayed" relative to
    assert evaluate_concept(1, "attention", rows).verdict == "never_probed_cold"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_gates_pure.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'adaptive_academy.engine.gates'`

- [ ] **Step 3: Implement the pure core + orchestrator**

```python
# src/adaptive_academy/engine/gates.py
"""Milestone gate verdicts — pure functions over existing evidence rows (spec §4.2).

A gate 'passes' only on evidence: every load-bearing concept under the milestone needs
(a) a DELAYED unassisted recall that held (the Decay-Check machinery, required not
suggested) and (b) an artifact-grade assessment at/above threshold. No LLM calls —
deterministic, testable, and impossible to sweet-talk (the anti-illusion-of-competence
design, parallel to Plan 1's attempt-gate and Plan 4's rules layer).
"""

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlmodel import Session, select

from adaptive_academy.models import Assessment, Concept, Milestone, ProgramTopicLink, Track

DELAY_DAYS = 7          # recall must be >= this many days after the prior engagement
HELD_RATIO = 0.85       # mirrors engine/decay.py: recall keeps >=85% of prior score
ARTIFACT_THRESHOLD = 0.7
ARTIFACT_KINDS = {"artifact_review", "teach", "productive_failure"}


def _naive_utc(dt: datetime) -> datetime:
    """SQLite round-trips datetimes tz-stripped; compare everything tz-naive."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


@dataclass
class ConceptEvidence:
    concept_id: int
    name: str
    delayed_ok: bool
    artifact_ok: bool
    verdict: str  # verified | stale | weak_artifact | never_probed_cold


@dataclass
class GateReport:
    milestone_id: int
    verdict: str  # passed | open | overridden
    reason: str
    concepts: list[ConceptEvidence]


def evaluate_concept(concept_id: int, name: str, assessments: list[Assessment]) -> ConceptEvidence:
    """Pure verdict for one concept from its assessment history.

    The MOST RECENT delayed recall decides held-vs-decayed: an old success must not
    mask later forgetting. A recall is 'delayed' iff it comes >= DELAY_DAYS after the
    closest prior non-recall assessment (fresh-engagement baseline).
    """
    rows = sorted(assessments, key=lambda a: a.id or 0)
    last_delayed_held: bool | None = None  # None = no delayed recall seen
    for i, r in enumerate(rows):
        if r.kind != "recall":
            continue
        prior = next((p for p in reversed(rows[:i]) if p.kind != "recall"), None)
        if prior is None:
            continue
        gap = _naive_utc(r.created_at) - _naive_utc(prior.created_at)
        if gap < timedelta(days=DELAY_DAYS):
            continue
        last_delayed_held = r.score >= prior.score * HELD_RATIO

    artifact_ok = any(
        a.kind in ARTIFACT_KINDS and a.score >= ARTIFACT_THRESHOLD for a in rows
    )
    delayed_ok = last_delayed_held is True

    if last_delayed_held is None:
        verdict = "never_probed_cold"
    elif last_delayed_held is False:
        verdict = "stale"
    elif not artifact_ok:
        verdict = "weak_artifact"
    else:
        verdict = "verified"
    return ConceptEvidence(concept_id=concept_id, name=name,
                           delayed_ok=delayed_ok, artifact_ok=artifact_ok, verdict=verdict)


def _milestone_load_bearing(session: Session, milestone: Milestone) -> list[Concept]:
    links = session.exec(
        select(ProgramTopicLink).where(
            ProgramTopicLink.milestone_id == milestone.id,
            ProgramTopicLink.status == "started",
        )
    ).all()
    topic_ids = [l.topic_id for l in links if l.topic_id is not None]
    if not topic_ids:
        return []
    return session.exec(
        select(Concept)
        .join(Track)
        .where(Track.topic_id.in_(topic_ids), Concept.is_load_bearing == True)  # noqa: E712
    ).all()


def milestone_gate(session: Session, milestone: Milestone) -> GateReport:
    """Compute the gate report and sync `milestone.gate_status`.

    Evidence-passed always wins (supersedes an override, spec §4.3). A stored 'passed'
    that no longer holds is honestly downgraded to 'open'. 'overridden' is sticky
    unless evidence passes.
    """
    concepts = _milestone_load_bearing(session, milestone)
    evidences: list[ConceptEvidence] = []
    for c in concepts:
        rows = session.exec(
            select(Assessment).where(Assessment.concept_id == c.id)
        ).all()
        evidences.append(evaluate_concept(c.id, c.name, rows))

    if not evidences:
        passed, reason = False, "no evidence yet: no started topics with load-bearing concepts"
    else:
        unverified = [e for e in evidences if e.verdict != "verified"]
        passed = not unverified
        reason = (
            "all load-bearing concepts verified (delayed recall held + artifact graded)"
            if passed
            else f"{len(unverified)} of {len(evidences)} load-bearing concepts unverified"
        )

    if passed:
        new_status = "passed"
    elif milestone.gate_status == "overridden":
        new_status = "overridden"
    else:
        new_status = "open"
    if new_status != milestone.gate_status:
        milestone.gate_status = new_status
        session.add(milestone)
        session.commit()
        session.refresh(milestone)

    return GateReport(milestone_id=milestone.id, verdict=milestone.gate_status,
                      reason=reason, concepts=evidences)
```

- [ ] **Step 4: Run pure tests to verify they pass**

Run: `uv run pytest tests/test_gates_pure.py -q`
Expected: 8 passed

- [ ] **Step 5: Write the failing orchestrator tests**

```python
# tests/test_gates_orchestrator.py
from datetime import datetime, timedelta

from adaptive_academy.engine.gates import milestone_gate
from adaptive_academy.models import (
    Assessment, Concept, Milestone, Program, ProgramTopicLink, Topic, Track,
)

T0 = datetime(2026, 7, 1, 12, 0, 0)


def _seed_milestone(session, *, started: bool = True):
    program = Program(title="P", goal_statement="g")
    session.add(program)
    session.commit()
    m = Milestone(program_id=program.id, title="M", order_index=0)
    session.add(m)
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="T")
    session.add(track)
    session.commit()
    lb = Concept(track_id=track.id, name="Attention", is_load_bearing=True)
    minor = Concept(track_id=track.id, name="Trivia", is_load_bearing=False)
    session.add(lb)
    session.add(minor)
    session.commit()
    link = ProgramTopicLink(milestone_id=m.id, topic_id=topic.id,
                            status="started" if started else "stub")
    session.add(link)
    session.commit()
    return m, lb


def test_no_started_topics_is_open_with_no_evidence(session):
    m, _ = _seed_milestone(session, started=False)
    report = milestone_gate(session, m)
    assert report.verdict == "open"
    assert "no evidence yet" in report.reason
    assert report.concepts == []


def test_verified_evidence_passes_and_persists(session):
    m, lb = _seed_milestone(session)
    session.add(Assessment(concept_id=lb.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=lb.id, kind="recall", prompt="p", score=0.85,
                           created_at=T0 + timedelta(days=8)))
    session.commit()
    report = milestone_gate(session, m)
    assert report.verdict == "passed"
    session.refresh(m)
    assert m.gate_status == "passed"
    # non-load-bearing concepts are not consulted
    assert [e.name for e in report.concepts] == ["Attention"]


def test_passed_downgrades_when_evidence_no_longer_holds(session):
    m, lb = _seed_milestone(session)
    m.gate_status = "passed"
    session.add(m)
    session.add(Assessment(concept_id=lb.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=lb.id, kind="recall", prompt="p", score=0.2,
                           created_at=T0 + timedelta(days=8)))  # decayed
    session.commit()
    report = milestone_gate(session, m)
    assert report.verdict == "open"
    assert report.concepts[0].verdict == "stale"


def test_override_is_sticky_until_evidence_passes(session):
    m, lb = _seed_milestone(session)
    m.gate_status = "overridden"
    session.add(m)
    session.commit()
    assert milestone_gate(session, m).verdict == "overridden"
    # now evidence arrives → passed supersedes the override
    session.add(Assessment(concept_id=lb.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=lb.id, kind="recall", prompt="p", score=0.85,
                           created_at=T0 + timedelta(days=8)))
    session.commit()
    assert milestone_gate(session, m).verdict == "passed"
```

- [ ] **Step 6: Run orchestrator tests to verify they pass**

Run: `uv run pytest tests/test_gates_orchestrator.py tests/test_gates_pure.py -q`
Expected: 12 passed (implementation already exists from Step 3; if any fail, fix `gates.py`, not the tests)

- [ ] **Step 7: Commit**

```bash
git add src/adaptive_academy/engine/gates.py tests/test_gates_pure.py tests/test_gates_orchestrator.py
git commit -m "feat(program): evidence-computed milestone gates (pure, no LLM)"
```

---

### Task 3: Program research fan-out (`engine/program_research.py` + prompt)

**Files:**
- Modify: `src/adaptive_academy/prompts.py` (add `PROGRAM_SYNTHESIS`)
- Create: `src/adaptive_academy/engine/program_research.py`
- Test: `tests/test_program_research.py`

**Interfaces:**
- Consumes: `SearchBrief`, `RawSource`, `ResearcherClient` from `adaptive_academy.llm.researcher_types`; `structured_json` from `adaptive_academy.llm.structured`; `LLMClient`; Task 1 models.
- Produces:
  - `PROGRAM_ANGLES: list[tuple[str, str]]` — angle keys: `phd_curricula`, `canonical_courses`, `practitioner_roadmaps`, `reading_lists`, `prerequisite_structures`
  - `build_program_briefs(goal: str, focus: str, n: int) -> list[SearchBrief]`
  - `parse_program_obj(data: dict) -> list[MilestoneDraft]` where `MilestoneDraft(title, success_criteria, depends_on: list[int], topics: list[TopicDraft])`, `TopicDraft(title, why, source_urls)`
  - `research_program(session, program, intent, *, researcher, llm, max_subagents=5, max_workers=5) -> ProgramResearchResult(milestones: list[Milestone], links: list[ProgramTopicLink], events: list[AgentEvent])` — raises `ValueError` if the program already has milestones.
  - `PROGRAM_SCHEMA: dict` (forced-tool-use JSON schema)

- [ ] **Step 1: Add the prompt**

In `src/adaptive_academy/prompts.py`, append (following the existing `Prompt(name, version, text)` pattern):

```python
PROGRAM_SYNTHESIS = Prompt(
    "program_synthesis",
    1,
    """You are the CurriculumDirector planning a LONG-HORIZON learning program for an
advanced adult self-directed learner. From the learner's intent and the researched
sources (real PhD curricula, qualifying-exam syllabi, canonical courses, practitioner
roadmaps, reading lists), propose 4-7 MILESTONES in dependency order.

Rules:
- Each milestone is a stage of weeks-to-months (e.g. "Math foundations",
  "Architectures from scratch"), with SUCCESS CRITERIA phrased so they are VERIFIABLE
  by delayed unassisted recall and graded artifacts — never "understand X"; instead
  "derive/implement/teach X without references".
- Each milestone lists 2-5 candidate TOPICS sized for a weeks-scale deep dive
  (each will become its own researched curriculum later). Give each a one-line "why"
  and the source URLs that justify it.
- depends_on lists the 0-based indices of earlier milestones it builds on.
- The FINAL milestone must be a capstone: critically read, reproduce, then extend a
  result from the primary literature of the learner's focus area.
- Respect the learner's stated prior knowledge: do not propose remedial topics they
  already clear.
Return via the tool call, nothing else.""",
)
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_program_research.py
import json

import pytest

from adaptive_academy.engine.program_research import (
    PROGRAM_ANGLES,
    build_program_briefs,
    parse_program_obj,
    research_program,
)
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import Milestone, Program, ProgramIntent

SYNTH = {
    "milestones": [
        {"title": "Math foundations", "success_criteria": "derive backprop cold",
         "depends_on": [],
         "topics": [{"title": "Linear algebra for DL", "why": "prereq",
                     "source_urls": ["https://example.com/la"]}]},
        {"title": "Architectures", "success_criteria": "implement a transformer unaided",
         "depends_on": [0, 5, 1],  # 5 is out of range, 1 is self → both dropped
         "topics": [{"title": "Attention from scratch", "why": "core"},
                    {"title": "Tokenization", "why": "core"}]},
    ]
}


def test_build_program_briefs_fills_goal_and_focus():
    briefs = build_program_briefs("PhD-level CS", "custom LLMs", 5)
    assert len(briefs) == 5
    assert [b.angle for b in briefs] == [a for a, _ in PROGRAM_ANGLES]
    assert "PhD-level CS" in briefs[0].query
    assert "custom LLMs" in briefs[0].query


def test_parse_program_obj_drops_invalid_depends_on():
    drafts = parse_program_obj(SYNTH)
    assert [d.title for d in drafts] == ["Math foundations", "Architectures"]
    assert drafts[1].depends_on == [0]  # forward/self refs dropped
    assert drafts[1].topics[0].title == "Attention from scratch"


def _program(session):
    p = Program(title="PhD prep", goal_statement="research-ready in custom LLMs")
    session.add(p)
    session.commit()
    intent = ProgramIntent(program_id=p.id, focus_area="custom LLMs",
                           prior_knowledge="MS-level math")
    session.add(intent)
    session.commit()
    return p, intent


def test_research_program_persists_milestones_and_links(session):
    p, intent = _program(session)
    researcher = ScriptedResearcherClient({
        "phd_curricula": [RawSource(title="MIT quals", url="https://mit.edu/q", tier=1)],
        "reading_lists": [RawSource(title="Papers", url="https://arxiv.org/x", tier=2)],
    })
    llm = ScriptedLLMClient([LLMResponse(text=json.dumps(SYNTH))])
    result = research_program(session, p, intent, researcher=researcher, llm=llm)

    assert [m.title for m in result.milestones] == ["Math foundations", "Architectures"]
    assert result.milestones[0].gate_status == "open"
    assert result.milestones[1].depends_on == [result.milestones[0].id]
    assert len(result.links) == 3
    assert all(l.status == "proposed" and l.topic_id is None for l in result.links)
    assert result.links[0].sources == ["https://example.com/la"]
    kinds = {e.kind for e in result.events}
    assert "program_research:plan" in kinds
    assert "program_research:synth" in kinds
    assert all(e.program_id == p.id for e in result.events)


def test_research_program_survives_single_angle_failure(session):
    p, intent = _program(session)

    class FlakyResearcher:
        def search(self, brief):
            if brief.angle == "phd_curricula":
                raise RuntimeError("529")
            return []

    llm = ScriptedLLMClient([LLMResponse(text=json.dumps(SYNTH))])
    result = research_program(session, p, intent, researcher=FlakyResearcher(), llm=llm)
    kinds = [e.kind for e in result.events]
    assert "program_research:subagent_error" in kinds
    assert len(result.milestones) == 2  # synthesis still ran


def test_research_program_refuses_second_run(session):
    p, intent = _program(session)
    session.add(Milestone(program_id=p.id, title="existing", order_index=0))
    session.commit()
    with pytest.raises(ValueError):
        research_program(session, p, intent,
                         researcher=ScriptedResearcherClient({}),
                         llm=ScriptedLLMClient([]))
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_program_research.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'adaptive_academy.engine.program_research'`

- [ ] **Step 4: Implement the module**

```python
# src/adaptive_academy/engine/program_research.py
"""Program-level research fan-out (spec §4.1) — Plan 2's muscle at program scale.

Fans out program-shaped angles (PhD curricula, canonical courses, roadmaps, reading
lists, prerequisite structures), then one structured synthesis call drafts milestones
+ candidate topics for human review. Nothing is materialized here beyond the proposal
rows (Milestone + ProgramTopicLink status=proposed).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from sqlmodel import Session, select

from adaptive_academy.llm.researcher_types import RawSource, ResearcherClient, SearchBrief
from adaptive_academy.llm.structured import structured_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.prompts import PROGRAM_SYNTHESIS
from adaptive_academy.models import AgentEvent, Milestone, Program, ProgramIntent, ProgramTopicLink

# (angle_key, query_template) — {goal}/{focus} are filled in. Order is the fan-out order.
PROGRAM_ANGLES: list[tuple[str, str]] = [
    ("phd_curricula", "PhD qualifying exam syllabi and graduate curricula for {goal} (focus: {focus})"),
    ("canonical_courses", "Canonical graduate courses and lecture series covering {goal} (focus: {focus})"),
    ("practitioner_roadmaps", "Practitioner roadmaps and self-study guides to expert level in {goal} (focus: {focus})"),
    ("reading_lists", "Primary-literature reading lists and seminal papers for {focus} within {goal}"),
    ("prerequisite_structures", "Prerequisite structure and foundational math/CS required for {goal} (focus: {focus})"),
]


def build_program_briefs(goal: str, focus: str, n: int) -> list[SearchBrief]:
    """Deterministic program-shaped fan-out angles. Caps at the defined ANGLES."""
    count = max(0, min(n, len(PROGRAM_ANGLES)))
    return [SearchBrief(angle=a, query=t.format(goal=goal, focus=focus or goal))
            for a, t in PROGRAM_ANGLES[:count]]


PROGRAM_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "milestones": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "success_criteria": {"type": "string"},
                    "depends_on": {"type": "array", "items": {"type": "integer"}},
                    "topics": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "title": {"type": "string"},
                                "why": {"type": "string"},
                                "source_urls": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["title"],
                        },
                    },
                },
                "required": ["title", "success_criteria", "topics"],
            },
        },
    },
    "required": ["milestones"],
}


@dataclass
class TopicDraft:
    title: str
    why: str = ""
    source_urls: list[str] = field(default_factory=list)


@dataclass
class MilestoneDraft:
    title: str
    success_criteria: str
    depends_on: list[int]
    topics: list[TopicDraft]


def parse_program_obj(data: dict) -> list[MilestoneDraft]:
    """Parse the synthesis payload; depends_on keeps only valid BACKWARD indices."""
    drafts: list[MilestoneDraft] = []
    for i, m in enumerate(data.get("milestones", []) or []):
        deps = [int(j) for j in (m.get("depends_on", []) or [])
                if isinstance(j, (int, float)) and 0 <= int(j) < i]
        topics = [TopicDraft(title=str(t.get("title", "")), why=str(t.get("why", "")),
                             source_urls=list(t.get("source_urls", []) or []))
                  for t in (m.get("topics", []) or []) if t.get("title")]
        drafts.append(MilestoneDraft(title=str(m.get("title", "")),
                                     success_criteria=str(m.get("success_criteria", "")),
                                     depends_on=sorted(set(deps)), topics=topics))
    return drafts


def _build_synthesis_user_msg(program: Program, intent: ProgramIntent,
                              sources: list[RawSource]) -> str:
    lines = [
        f"PROGRAM GOAL: {program.goal_statement or program.title}",
        f"FOCUS AREA: {intent.focus_area}",
        f"TARGET DEPTH: {intent.target_depth}",
        f"PRIOR KNOWLEDGE: {intent.prior_knowledge}",
        f"WEEKLY TIME BUDGET: {intent.weekly_time_budget}",
        f"HORIZON: {intent.horizon}",
        "",
        "<<<SOURCES>>>",
    ]
    for s in sources:
        lines.append(f"- [{s.angle}] {s.title} ({s.url}) — {s.summary}".rstrip(" —"))
    lines.append("<<<END_SOURCES>>>")
    return "\n".join(lines)


@dataclass
class ProgramResearchResult:
    milestones: list[Milestone]
    links: list[ProgramTopicLink]
    events: list[AgentEvent]


def research_program(
    session: Session,
    program: Program,
    intent: ProgramIntent,
    *,
    researcher: ResearcherClient,
    llm: LLMClient,
    max_subagents: int = 5,
    max_workers: int = 5,
) -> ProgramResearchResult:
    """Fan out, synthesize a milestone proposal, persist proposal rows, trace."""
    existing = session.exec(
        select(Milestone).where(Milestone.program_id == program.id)
    ).first()
    if existing is not None:
        raise ValueError("program already has a proposal")

    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(program_id=program.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    briefs = build_program_briefs(program.goal_statement or program.title,
                                  intent.focus_area, max_subagents)
    emit("program_research:plan", f"{len(briefs)} briefs")

    per_brief: list[list[RawSource]] = [[] for _ in briefs]
    failures: dict[int, str] = {}
    if briefs:
        with ThreadPoolExecutor(max_workers=max(1, min(max_workers, len(briefs)))) as ex:
            futures = {ex.submit(researcher.search, b): i for i, b in enumerate(briefs)}
            for fut in as_completed(futures):
                idx = futures[fut]
                try:
                    per_brief[idx] = fut.result()
                except Exception as e:  # noqa: BLE001
                    failures[idx] = type(e).__name__

    raw: list[RawSource] = []
    for i, brief in enumerate(briefs):
        for s in per_brief[i]:
            s.angle = brief.angle
        if i in failures:
            emit("program_research:subagent_error", f"{brief.angle}: {failures[i]}")
        else:
            emit("program_research:subagent", f"{brief.angle}: {len(per_brief[i])} sources")
        raw.extend(per_brief[i])

    emit("prompt", PROGRAM_SYNTHESIS.tag)
    data = structured_json(
        llm, PROGRAM_SYNTHESIS,
        [{"role": "user", "content": _build_synthesis_user_msg(program, intent, raw)}],
        schema=PROGRAM_SCHEMA, tool_name="emit_program",
    )
    drafts = parse_program_obj(data)
    emit("program_research:synth", f"{len(drafts)} milestones proposed")

    milestones: list[Milestone] = []
    for i, d in enumerate(drafts):
        m = Milestone(program_id=program.id, title=d.title,
                      success_criteria=d.success_criteria, order_index=i)
        session.add(m)
        session.commit()
        session.refresh(m)
        milestones.append(m)
    # second pass: map draft indices → milestone ids
    for i, d in enumerate(drafts):
        if d.depends_on:
            milestones[i].depends_on = [milestones[j].id for j in d.depends_on]
            session.add(milestones[i])

    links: list[ProgramTopicLink] = []
    for i, d in enumerate(drafts):
        for t in d.topics:
            link = ProgramTopicLink(milestone_id=milestones[i].id, status="proposed",
                                    proposed_title=t.title, why=t.why,
                                    sources=t.source_urls)
            session.add(link)
            links.append(link)

    emit("program_research:done", f"{len(links)} topic candidates")
    session.commit()
    for m in milestones:
        session.refresh(m)
    for link in links:
        session.refresh(link)
    return ProgramResearchResult(milestones=milestones, links=links, events=events)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_program_research.py -q`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add src/adaptive_academy/prompts.py src/adaptive_academy/engine/program_research.py tests/test_program_research.py
git commit -m "feat(program): program-level research fan-out drafting milestones + topic candidates"
```

---

### Task 4: Concept alias carryover (`engine/aliases.py`)

**Files:**
- Create: `src/adaptive_academy/engine/aliases.py`
- Test: `tests/test_aliases.py`

**Interfaces:**
- Consumes: Task 1 models; existing `Concept`, `KnowledgeEstimate`, `Assessment`, `Track`.
- Produces:
  - `normalize_name(name: str) -> str`
  - `AliasResult(registered: int, seeded: list[tuple[int, str]])` — seeded = (concept_id, level)
  - `apply_program_aliases(session: Session, topic_id: int) -> AliasResult` — no-op (`AliasResult(0, [])`) when the topic is not a started program link. Called by the curriculum route in Task 5.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_aliases.py
from sqlmodel import select

from adaptive_academy.engine.aliases import apply_program_aliases, normalize_name
from adaptive_academy.models import (
    Assessment, Concept, ConceptAlias, KnowledgeEstimate, Milestone, Program,
    ProgramTopicLink, Topic, Track,
)


def test_normalize_name():
    assert normalize_name("  Self-Attention ") == "self-attention"
    assert normalize_name("BACKPROP") == "backprop"


def _seed_topic(session, program, milestone, names_levels, *, assessed=None):
    """Create topic+track+concepts(+estimates) and a started program link."""
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="T")
    session.add(track)
    session.commit()
    concepts = []
    for name, level in names_levels:
        c = Concept(track_id=track.id, name=name, is_load_bearing=True)
        session.add(c)
        session.commit()
        session.refresh(c)
        session.add(KnowledgeEstimate(concept_id=c.id, level=level))
        concepts.append(c)
    for cid, score in (assessed or []):
        session.add(Assessment(concept_id=concepts[cid].id, kind="self_explanation",
                               prompt="p", score=score))
    session.add(ProgramTopicLink(milestone_id=milestone.id, topic_id=topic.id,
                                 status="started"))
    session.commit()
    return topic, concepts


def _program(session):
    p = Program(title="P", goal_statement="g")
    session.add(p)
    session.commit()
    m = Milestone(program_id=p.id, title="M", order_index=0)
    session.add(m)
    session.commit()
    return p, m


def test_topic_outside_program_is_noop(session):
    topic = Topic(title="standalone")
    session.add(topic)
    session.commit()
    result = apply_program_aliases(session, topic.id)
    assert result.registered == 0 and result.seeded == []


def test_first_topic_registers_groups_second_topic_seeds(session):
    p, m = _program(session)
    topic1, first = _seed_topic(session, p, m,
                                [("Attention", "low"), ("Tokenization", "medium")],
                                assessed=[(0, 0.4)])
    r1 = apply_program_aliases(session, topic1.id)
    assert r1.registered == 2 and r1.seeded == []

    # second topic re-mentions "attention" (case-insensitive) with the cold default "high"
    topic2, second = _seed_topic(session, p, m, [("attention", "high"), ("RLHF", "high")])
    r2 = apply_program_aliases(session, topic2.id)
    assert r2.registered == 2  # both concepts join alias groups (one existing, one new)
    assert r2.seeded == [(second[0].id, "low")]  # seeded from most-recently-assessed member
    est = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == second[0].id)
    ).first()
    assert est.level == "low"


def test_apply_is_idempotent(session):
    p, m = _program(session)
    topic, _ = _seed_topic(session, p, m, [("Attention", "low")])
    apply_program_aliases(session, topic.id)
    r2 = apply_program_aliases(session, topic.id)
    assert r2.registered == 0  # already-aliased concepts are skipped
    assert len(session.exec(select(ConceptAlias)).all()) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_aliases.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'adaptive_academy.engine.aliases'`

- [ ] **Step 3: Implement the module**

```python
# src/adaptive_academy/engine/aliases.py
"""Cross-topic knowledge carryover inside a Program (spec §4.4).

After a program topic's curriculum materializes concepts, link them by normalized name
to prior concepts in the same program (ConceptAlias groups). A matched concept's
KnowledgeEstimate is seeded from the group's most recently assessed member instead of
the cold default — the Tutor opens at the right assistance level and the curriculum
skips what the learner verifiably kept. Name-match only (Plan 6 pattern); LLM-assisted
matching is deferred until this demonstrably misses.
"""

from dataclasses import dataclass, field

from sqlmodel import Session, select

from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    ConceptAlias,
    KnowledgeEstimate,
    Milestone,
    ProgramTopicLink,
    Track,
)


def normalize_name(name: str) -> str:
    return name.strip().casefold()


@dataclass
class AliasResult:
    registered: int = 0
    seeded: list[tuple[int, str]] = field(default_factory=list)  # (concept_id, level)


def _program_for_topic(session: Session, topic_id: int) -> int | None:
    link = session.exec(
        select(ProgramTopicLink).where(
            ProgramTopicLink.topic_id == topic_id,
            ProgramTopicLink.status == "started",
        )
    ).first()
    if link is None:
        return None
    milestone = session.get(Milestone, link.milestone_id)
    return milestone.program_id if milestone else None


def _group_level(session: Session, member_ids: list[int]) -> str | None:
    """Level of the group's most recently assessed member; falls back to the
    newest member's estimate when nothing was ever assessed."""
    if not member_ids:
        return None
    latest = session.exec(
        select(Assessment)
        .where(Assessment.concept_id.in_(member_ids))
        .order_by(Assessment.id.desc())
    ).first()
    source_id = latest.concept_id if latest else max(member_ids)
    est = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == source_id)
    ).first()
    return est.level if est else None


def apply_program_aliases(session: Session, topic_id: int) -> AliasResult:
    """Register this topic's concepts into the program's alias groups; seed estimates
    for matches. Idempotent: concepts already aliased are skipped. No-op for topics
    outside a program."""
    program_id = _program_for_topic(session, topic_id)
    if program_id is None:
        return AliasResult()

    concepts = session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)
    ).all()
    result = AliasResult()
    for c in concepts:
        already = session.exec(
            select(ConceptAlias).where(ConceptAlias.concept_id == c.id)
        ).first()
        if already is not None:
            continue
        canonical = normalize_name(c.name)
        group = session.exec(
            select(ConceptAlias).where(
                ConceptAlias.program_id == program_id,
                ConceptAlias.canonical_name == canonical,
            )
        ).all()
        if group:
            level = _group_level(session, [g.concept_id for g in group])
            est = session.exec(
                select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == c.id)
            ).first()
            if level is not None and est is not None and est.level != level:
                est.level = level
                session.add(est)
                result.seeded.append((c.id, level))
        session.add(ConceptAlias(program_id=program_id, canonical_name=canonical,
                                 concept_id=c.id))
        result.registered += 1

    if result.registered:
        session.add(AgentEvent(
            topic_id=topic_id, kind="program:alias",
            detail=f"{result.registered} registered, {len(result.seeded)} seeded"))
    session.commit()
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_aliases.py -q`
Expected: 4 passed

Note: `test_first_topic_registers_groups_second_topic_seeds` asserts `r2.seeded == [(second[0].id, "low")]` — this works because the second concept's default estimate is `"high"` and the seed changes it. If a seed level equals the existing level the concept is registered but not reported as seeded (no-op write) — that is intended behavior.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/aliases.py tests/test_aliases.py
git commit -m "feat(program): ConceptAlias carryover seeds knowledge estimates across program topics"
```

---

### Task 5: API — schemas, `routes_programs.py`, wiring, alias hook

**Files:**
- Modify: `src/adaptive_academy/api/schemas.py` (append program schemas)
- Create: `src/adaptive_academy/api/routes_programs.py`
- Modify: `src/adaptive_academy/api/app.py` (include router)
- Modify: `src/adaptive_academy/api/routes_topics.py` (alias hook in `generate_curriculum_route`; `GET /api/topics/{id}/program-context`)
- Test: `tests/test_api_programs.py`

**Interfaces:**
- Consumes: Tasks 1–4 (`research_program`, `milestone_gate`, `apply_program_aliases`, models).
- Produces (endpoints):
  - `POST /api/programs` body `CreateProgramIn{title, goal_statement, target_depth?, prior_knowledge?, weekly_time_budget?, horizon?, focus_area?}` → `ProgramOut`
  - `GET /api/programs` → `list[ProgramOut]`
  - `GET /api/programs/{pid}` → `ProgramDetailOut{program, milestones: [MilestoneOut{..., links: [LinkOut]}]}`
  - `POST /api/programs/{pid}/research` → `ProgramDetailOut` (400 if proposal exists / no intent)
  - `PUT /api/programs/{pid}/milestones/{mid}` body `MilestoneUpdateIn{title?, success_criteria?, order_index?, depends_on?}` → `MilestoneOut`
  - `POST /api/programs/{pid}/accept` body `AcceptIn{accepted_link_ids, pruned_link_ids}` → `ProgramDetailOut` (proposed→stub/pruned)
  - `POST /api/programs/{pid}/links/{link_id}/start` → `StartOut{topic_id}` (creates Topic+TopicIntent; idempotent when already started)
  - `GET /api/programs/{pid}/milestones/{mid}/gate` → `GateReportOut{milestone_id, verdict, reason, concepts: [ConceptEvidenceOut]}`
  - `POST /api/programs/{pid}/milestones/{mid}/override` body `OverrideIn{reason}` → `MilestoneOut` (400 on blank reason)
  - `GET /api/programs/{pid}/events` → `list[EventOut]`
  - `GET /api/topics/{topic_id}/program-context` → `ProgramContextOut{program_id, program_title, milestone_id, milestone_title, gate_status, unverified: list[str]}` (404 when topic not in a program)

- [ ] **Step 1: Append schemas**

In `src/adaptive_academy/api/schemas.py`, append (Pydantic `BaseModel`s, matching file style):

```python
class CreateProgramIn(BaseModel):
    title: str
    goal_statement: str = ""
    target_depth: str = ""
    prior_knowledge: str = ""
    weekly_time_budget: str = ""
    horizon: str = ""
    focus_area: str = ""


class ProgramOut(BaseModel):
    id: int
    title: str
    goal_statement: str
    status: str
    milestone_count: int = 0


class LinkOut(BaseModel):
    id: int
    status: str
    proposed_title: str
    why: str
    sources: list[str] = []
    topic_id: Optional[int] = None


class MilestoneOut(BaseModel):
    id: int
    title: str
    success_criteria: str
    order_index: int
    gate_status: str
    depends_on: list[int] = []
    override_reason: str = ""
    links: list[LinkOut] = []


class ProgramDetailOut(BaseModel):
    program: ProgramOut
    milestones: list[MilestoneOut]


class MilestoneUpdateIn(BaseModel):
    title: Optional[str] = None
    success_criteria: Optional[str] = None
    order_index: Optional[int] = None
    depends_on: Optional[list[int]] = None


class AcceptIn(BaseModel):
    accepted_link_ids: list[int] = []
    pruned_link_ids: list[int] = []


class StartOut(BaseModel):
    topic_id: int


class OverrideIn(BaseModel):
    reason: str


class ConceptEvidenceOut(BaseModel):
    concept_id: int
    name: str
    delayed_ok: bool
    artifact_ok: bool
    verdict: str


class GateReportOut(BaseModel):
    milestone_id: int
    verdict: str
    reason: str
    concepts: list[ConceptEvidenceOut]


class ProgramContextOut(BaseModel):
    program_id: int
    program_title: str
    milestone_id: int
    milestone_title: str
    gate_status: str
    unverified: list[str] = []
```

- [ ] **Step 2: Write the failing API tests**

```python
# tests/test_api_programs.py
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import Assessment, Milestone, TopicIntent

SYNTH = {
    "milestones": [
        {"title": "Math foundations", "success_criteria": "derive backprop cold",
         "depends_on": [],
         "topics": [{"title": "Linear algebra for DL", "why": "prereq"}]},
        {"title": "Architectures", "success_criteria": "transformer unaided",
         "depends_on": [0],
         "topics": [{"title": "Attention from scratch", "why": "core"}]},
    ]
}


def _client(session: Session, llm_payloads: list[str] | None = None) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    payloads = llm_payloads or [json.dumps(SYNTH)]
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=p) for p in payloads])
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "phd_curricula": [RawSource(title="Quals", url="https://mit.edu/q", tier=1)],
    })
    return TestClient(app)


def _make_program(client) -> int:
    r = client.post("/api/programs", json={
        "title": "PhD prep", "goal_statement": "research-ready in custom LLMs",
        "focus_area": "custom LLMs", "prior_knowledge": "MS-level math",
        "weekly_time_budget": "10h", "horizon": "2 years", "target_depth": "phd"})
    assert r.status_code == 200
    return r.json()["id"]


def test_create_list_get_program(session):
    client = _client(session)
    pid = _make_program(client)
    assert client.get("/api/programs").json()[0]["title"] == "PhD prep"
    detail = client.get(f"/api/programs/{pid}").json()
    assert detail["program"]["id"] == pid
    assert detail["milestones"] == []
    assert client.get("/api/programs/999").status_code == 404


def test_research_accept_start_flow(session):
    client = _client(session)
    pid = _make_program(client)

    r = client.post(f"/api/programs/{pid}/research")
    assert r.status_code == 200
    detail = r.json()
    assert [m["title"] for m in detail["milestones"]] == ["Math foundations", "Architectures"]
    links = [l for m in detail["milestones"] for l in m["links"]]
    assert all(l["status"] == "proposed" for l in links)

    # second research run refused
    assert client.post(f"/api/programs/{pid}/research").status_code == 400

    # accept one, prune one
    r = client.post(f"/api/programs/{pid}/accept", json={
        "accepted_link_ids": [links[0]["id"]], "pruned_link_ids": [links[1]["id"]]})
    assert r.status_code == 200
    statuses = {l["id"]: l["status"]
                for m in r.json()["milestones"] for l in m["links"]}
    assert statuses[links[0]["id"]] == "stub"
    assert statuses[links[1]["id"]] == "pruned"

    # start the stub → creates Topic + prefilled intent, flips to started
    r = client.post(f"/api/programs/{pid}/links/{links[0]['id']}/start")
    assert r.status_code == 200
    topic_id = r.json()["topic_id"]
    intent = session.exec(select(TopicIntent).where(TopicIntent.topic_id == topic_id)).first()
    assert "research-ready in custom LLMs" in intent.goal
    assert intent.prior_knowledge == "MS-level math"

    # idempotent: starting again returns the same topic
    assert client.post(f"/api/programs/{pid}/links/{links[0]['id']}/start").json()["topic_id"] == topic_id
    # starting a pruned link is a 400
    assert client.post(f"/api/programs/{pid}/links/{links[1]['id']}/start").status_code == 400


def test_milestone_edit_and_override(session):
    client = _client(session)
    pid = _make_program(client)
    client.post(f"/api/programs/{pid}/research")
    mid = client.get(f"/api/programs/{pid}").json()["milestones"][0]["id"]

    r = client.put(f"/api/programs/{pid}/milestones/{mid}",
                   json={"title": "Math core", "success_criteria": "new bar"})
    assert r.status_code == 200
    assert r.json()["title"] == "Math core"

    assert client.post(f"/api/programs/{pid}/milestones/{mid}/override",
                       json={"reason": "  "}).status_code == 400
    r = client.post(f"/api/programs/{pid}/milestones/{mid}/override",
                    json={"reason": "moving on, verified offline"})
    assert r.status_code == 200
    assert r.json()["gate_status"] == "overridden"
    events = client.get(f"/api/programs/{pid}/events").json()
    assert any(e["kind"] == "program:gate_override" for e in events)


def test_gate_endpoint_and_program_context(session):
    client = _client(session)
    pid = _make_program(client)
    client.post(f"/api/programs/{pid}/research")
    detail = client.get(f"/api/programs/{pid}").json()
    mid = detail["milestones"][0]["id"]
    link_id = detail["milestones"][0]["links"][0]["id"]
    client.post(f"/api/programs/{pid}/accept", json={"accepted_link_ids": [link_id],
                                                     "pruned_link_ids": []})
    topic_id = client.post(f"/api/programs/{pid}/links/{link_id}/start").json()["topic_id"]

    # empty gate: no curriculum/concepts yet
    r = client.get(f"/api/programs/{pid}/milestones/{mid}/gate")
    assert r.status_code == 200
    assert r.json()["verdict"] == "open"
    assert "no evidence yet" in r.json()["reason"]

    # materialize a concept + evidence by hand (curriculum pipeline tested elsewhere)
    from adaptive_academy.models import Concept, KnowledgeEstimate, Track
    track = Track(topic_id=topic_id, title="T")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="Attention", is_load_bearing=True)
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id))
    t0 = datetime(2026, 7, 1)
    session.add(Assessment(concept_id=concept.id, kind="teach", prompt="p",
                           score=0.9, created_at=t0))
    session.add(Assessment(concept_id=concept.id, kind="recall", prompt="p",
                           score=0.85, created_at=t0 + timedelta(days=8)))
    session.commit()

    r = client.get(f"/api/programs/{pid}/milestones/{mid}/gate")
    assert r.json()["verdict"] == "passed"
    assert r.json()["concepts"][0]["verdict"] == "verified"

    ctx = client.get(f"/api/topics/{topic_id}/program-context")
    assert ctx.status_code == 200
    assert ctx.json()["milestone_id"] == mid
    assert ctx.json()["gate_status"] == "passed"
    assert ctx.json()["unverified"] == []

    # a topic outside any program has no context
    lone = client.post("/api/topics", json={"title": "lone", "goal": "g"}).json()["id"]
    assert client.get(f"/api/topics/{lone}/program-context").status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/test_api_programs.py -q`
Expected: FAIL (404s — routes don't exist yet; the `create_app` import works)

- [ ] **Step 4: Implement `routes_programs.py`**

```python
# src/adaptive_academy/api/routes_programs.py
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.api.schemas import (
    AcceptIn,
    ConceptEvidenceOut,
    CreateProgramIn,
    EventOut,
    GateReportOut,
    LinkOut,
    MilestoneOut,
    MilestoneUpdateIn,
    OverrideIn,
    ProgramDetailOut,
    ProgramOut,
    StartOut,
)
from adaptive_academy.engine.gates import milestone_gate
from adaptive_academy.engine.program_research import research_program
from adaptive_academy.llm.researcher_types import ResearcherClient
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Milestone,
    Program,
    ProgramIntent,
    ProgramTopicLink,
    Topic,
    TopicIntent,
    _now,
)

router = APIRouter(prefix="/api/programs", tags=["programs"])


def _program_or_404(session: Session, program_id: int) -> Program:
    program = session.get(Program, program_id)
    if program is None:
        raise HTTPException(404, "program not found")
    return program


def _milestone_or_404(session: Session, program_id: int, milestone_id: int) -> Milestone:
    m = session.get(Milestone, milestone_id)
    if m is None or m.program_id != program_id:
        raise HTTPException(404, "milestone not found")
    return m


def _link_out(link: ProgramTopicLink) -> LinkOut:
    return LinkOut(id=link.id, status=link.status, proposed_title=link.proposed_title,
                   why=link.why, sources=link.sources, topic_id=link.topic_id)


def _milestone_out(session: Session, m: Milestone) -> MilestoneOut:
    links = session.exec(
        select(ProgramTopicLink).where(ProgramTopicLink.milestone_id == m.id)
    ).all()
    return MilestoneOut(id=m.id, title=m.title, success_criteria=m.success_criteria,
                        order_index=m.order_index, gate_status=m.gate_status,
                        depends_on=m.depends_on, override_reason=m.override_reason,
                        links=[_link_out(l) for l in links])


def _program_out(session: Session, p: Program) -> ProgramOut:
    count = len(session.exec(select(Milestone).where(Milestone.program_id == p.id)).all())
    return ProgramOut(id=p.id, title=p.title, goal_statement=p.goal_statement,
                      status=p.status, milestone_count=count)


def _detail(session: Session, p: Program) -> ProgramDetailOut:
    milestones = session.exec(
        select(Milestone).where(Milestone.program_id == p.id).order_by(Milestone.order_index)
    ).all()
    return ProgramDetailOut(program=_program_out(session, p),
                            milestones=[_milestone_out(session, m) for m in milestones])


@router.post("", response_model=ProgramOut)
def create_program(body: CreateProgramIn, session: Session = Depends(get_session)):
    program = Program(title=body.title, goal_statement=body.goal_statement)
    session.add(program)
    session.commit()
    session.refresh(program)
    session.add(ProgramIntent(
        program_id=program.id, target_depth=body.target_depth,
        prior_knowledge=body.prior_knowledge, weekly_time_budget=body.weekly_time_budget,
        horizon=body.horizon, focus_area=body.focus_area))
    session.commit()
    return _program_out(session, program)


@router.get("", response_model=list[ProgramOut])
def list_programs(session: Session = Depends(get_session)):
    return [_program_out(session, p) for p in session.exec(select(Program)).all()]


@router.get("/{program_id}", response_model=ProgramDetailOut)
def get_program(program_id: int, session: Session = Depends(get_session)):
    return _detail(session, _program_or_404(session, program_id))


@router.post("/{program_id}/research", response_model=ProgramDetailOut)
def run_program_research(
    program_id: int,
    session: Session = Depends(get_session),
    researcher: ResearcherClient = Depends(get_researcher),
    llm: LLMClient = Depends(get_llm),
):
    program = _program_or_404(session, program_id)
    intent = session.exec(
        select(ProgramIntent).where(ProgramIntent.program_id == program_id)
    ).first()
    if intent is None:
        raise HTTPException(400, "program has no intent")
    try:
        research_program(session, program, intent, researcher=researcher, llm=llm)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return _detail(session, program)


@router.put("/{program_id}/milestones/{milestone_id}", response_model=MilestoneOut)
def update_milestone(
    program_id: int, milestone_id: int, body: MilestoneUpdateIn,
    session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    m = _milestone_or_404(session, program_id, milestone_id)
    if body.title is not None:
        m.title = body.title
    if body.success_criteria is not None:
        m.success_criteria = body.success_criteria
    if body.order_index is not None:
        m.order_index = body.order_index
    if body.depends_on is not None:
        m.depends_on = body.depends_on
    program.updated_at = _now()
    session.add(m)
    session.add(program)
    session.commit()
    session.refresh(m)
    return _milestone_out(session, m)


@router.post("/{program_id}/accept", response_model=ProgramDetailOut)
def accept_program(
    program_id: int, body: AcceptIn, session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    milestone_ids = [m.id for m in session.exec(
        select(Milestone).where(Milestone.program_id == program_id)).all()]
    links = session.exec(
        select(ProgramTopicLink).where(ProgramTopicLink.milestone_id.in_(milestone_ids))
    ).all() if milestone_ids else []
    by_id = {l.id: l for l in links}
    for lid in body.accepted_link_ids:
        if lid in by_id and by_id[lid].status == "proposed":
            by_id[lid].status = "stub"
    for lid in body.pruned_link_ids:
        if lid in by_id and by_id[lid].status == "proposed":
            by_id[lid].status = "pruned"
    program.updated_at = _now()
    session.add(program)
    session.commit()
    return _detail(session, program)


@router.post("/{program_id}/links/{link_id}/start", response_model=StartOut)
def start_link(
    program_id: int, link_id: int, session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    link = session.get(ProgramTopicLink, link_id)
    if link is None:
        raise HTTPException(404, "link not found")
    milestone = session.get(Milestone, link.milestone_id)
    if milestone is None or milestone.program_id != program_id:
        raise HTTPException(404, "link not found")
    if link.status == "started" and link.topic_id is not None:
        return StartOut(topic_id=link.topic_id)  # idempotent
    if link.status != "stub":
        raise HTTPException(400, f"link is {link.status}, not stub")

    intent = session.exec(
        select(ProgramIntent).where(ProgramIntent.program_id == program_id)
    ).first()
    topic = Topic(title=link.proposed_title)
    session.add(topic)
    session.commit()
    session.refresh(topic)
    goal = (f"{link.proposed_title} — part of program '{program.title}' "
            f"({program.goal_statement}). Milestone: {milestone.title} — "
            f"{milestone.success_criteria}")
    session.add(TopicIntent(
        topic_id=topic.id, goal=goal,
        prior_knowledge=intent.prior_knowledge if intent else "",
        time_budget=intent.weekly_time_budget if intent else ""))
    link.topic_id = topic.id
    link.status = "started"
    program.updated_at = _now()
    session.add(link)
    session.add(program)
    session.add(AgentEvent(program_id=program_id, kind="program:topic_started",
                           detail=f"link {link.id} → topic {topic.id}"))
    session.commit()
    return StartOut(topic_id=topic.id)


@router.get("/{program_id}/milestones/{milestone_id}/gate", response_model=GateReportOut)
def get_gate(
    program_id: int, milestone_id: int, session: Session = Depends(get_session),
):
    _program_or_404(session, program_id)
    m = _milestone_or_404(session, program_id, milestone_id)
    report = milestone_gate(session, m)
    return GateReportOut(
        milestone_id=report.milestone_id, verdict=report.verdict, reason=report.reason,
        concepts=[ConceptEvidenceOut(concept_id=e.concept_id, name=e.name,
                                     delayed_ok=e.delayed_ok, artifact_ok=e.artifact_ok,
                                     verdict=e.verdict) for e in report.concepts])


@router.post("/{program_id}/milestones/{milestone_id}/override", response_model=MilestoneOut)
def override_gate(
    program_id: int, milestone_id: int, body: OverrideIn,
    session: Session = Depends(get_session),
):
    program = _program_or_404(session, program_id)
    m = _milestone_or_404(session, program_id, milestone_id)
    reason = body.reason.strip()
    if not reason:
        raise HTTPException(400, "override requires a reason")
    m.gate_status = "overridden"
    m.override_reason = reason
    program.updated_at = _now()
    session.add(m)
    session.add(program)
    session.add(AgentEvent(program_id=program_id, kind="program:gate_override",
                           detail=f"milestone {m.id}: {reason}"))
    session.commit()
    session.refresh(m)
    return _milestone_out(session, m)


@router.get("/{program_id}/events", response_model=list[EventOut])
def list_program_events(program_id: int, session: Session = Depends(get_session)):
    _program_or_404(session, program_id)
    rows = session.exec(
        select(AgentEvent).where(AgentEvent.program_id == program_id)
        .order_by(AgentEvent.id)
    ).all()
    return [EventOut(kind=e.kind, detail=e.detail) for e in rows]
```

Note: `_now` is imported from `adaptive_academy.models` (it exists there as a module-level helper). If ruff objects to importing a private name, add a public `now_utc = _now` alias in `models.py` and import that instead — do whichever keeps `uv run ruff check .` green.

- [ ] **Step 5: Wire the router and the topic-side endpoints**

In `src/adaptive_academy/api/app.py`, register the router exactly like the existing ones (find the block of `app.include_router(...)` calls in `create_app` and add):

```python
from adaptive_academy.api.routes_programs import router as programs_router
# inside create_app(), with the other include_router calls:
app.include_router(programs_router)
```

In `src/adaptive_academy/api/routes_topics.py`:

1. Add imports: `from adaptive_academy.engine.aliases import apply_program_aliases`, `from adaptive_academy.engine.gates import milestone_gate`, and add `Milestone, Program, ProgramTopicLink` to the models import plus `ProgramContextOut` to the schemas import.

2. In `generate_curriculum_route`, immediately after `result = generate_curriculum(...)` and before `return`:

```python
    apply_program_aliases(session, topic_id)
```

3. Append the program-context endpoint at the end of the file:

```python
@router.get("/{topic_id}/program-context", response_model=ProgramContextOut)
def get_program_context(topic_id: int, session: Session = Depends(get_session)):
    link = session.exec(
        select(ProgramTopicLink).where(ProgramTopicLink.topic_id == topic_id)
    ).first()
    if link is None:
        raise HTTPException(404, "topic is not part of a program")
    milestone = session.get(Milestone, link.milestone_id)
    program = session.get(Program, milestone.program_id)
    report = milestone_gate(session, milestone)
    return ProgramContextOut(
        program_id=program.id, program_title=program.title,
        milestone_id=milestone.id, milestone_title=milestone.title,
        gate_status=report.verdict,
        unverified=[e.name for e in report.concepts if e.verdict != "verified"])
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_api_programs.py -q`
Expected: 4 passed. Then `uv run pytest -q` — full suite green (existing curriculum tests must still pass with the alias hook, which no-ops for non-program topics). Then `uv run ruff check .` — clean.

- [ ] **Step 7: Commit**

```bash
git add src/adaptive_academy/api/ tests/test_api_programs.py
git commit -m "feat(program): programs API — research/accept/start, gates, override, program-context"
```

---

### Task 6: Frontend — types, api client, `/programs` + `/programs/new`

**Files:**
- Modify: `frontend/src/lib/types.ts` (append program types)
- Modify: `frontend/src/lib/api.ts` (append program calls)
- Create: `frontend/src/routes/programs/+page.svelte`
- Create: `frontend/src/routes/programs/new/+page.svelte`
- Modify: `frontend/src/lib/shell/Rail.svelte` (nav entry)
- Test: `frontend/src/lib/programs.test.ts` (+ helper in `frontend/src/lib/programs.ts`)

**Interfaces:**
- Consumes: Task 5 endpoints.
- Produces: `api.listPrograms()`, `api.createProgram(body)`, `api.getProgram(id)`, `api.programResearch(id)`, `api.acceptProgram(id, body)`, `api.startLink(pid, linkId)`, `api.milestoneGate(pid, mid)`, `api.overrideGate(pid, mid, reason)`, `api.updateMilestone(pid, mid, body)`, `api.programContext(topicId)`; types `Program`, `ProgramDetail`, `MilestoneInfo`, `LinkInfo`, `GateReport`, `ConceptEvidence`, `ProgramContext`; helper `gateBadge(verdict)`.

- [ ] **Step 1: Write the failing helper test**

```typescript
// frontend/src/lib/programs.test.ts
import { describe, expect, it } from 'vitest';
import { gateBadge } from './programs';

describe('gateBadge', () => {
  it('maps gate/evidence verdicts to label + tone', () => {
    expect(gateBadge('passed')).toEqual({ label: 'Verified', tone: 'ok' });
    expect(gateBadge('overridden')).toEqual({ label: '⚠ Unverified (overridden)', tone: 'warn' });
    expect(gateBadge('open')).toEqual({ label: 'Open', tone: 'muted' });
    expect(gateBadge('verified')).toEqual({ label: 'Verified', tone: 'ok' });
    expect(gateBadge('stale')).toEqual({ label: 'Decayed', tone: 'warn' });
    expect(gateBadge('weak_artifact')).toEqual({ label: 'No artifact', tone: 'warn' });
    expect(gateBadge('never_probed_cold')).toEqual({ label: 'Never probed cold', tone: 'muted' });
  });
});
```

Run: `cd frontend && npx vitest run src/lib/programs.test.ts` — Expected: FAIL (module missing).

- [ ] **Step 2: Implement the helper**

```typescript
// frontend/src/lib/programs.ts
export type BadgeTone = 'ok' | 'warn' | 'muted';

const BADGES: Record<string, { label: string; tone: BadgeTone }> = {
  passed: { label: 'Verified', tone: 'ok' },
  verified: { label: 'Verified', tone: 'ok' },
  overridden: { label: '⚠ Unverified (overridden)', tone: 'warn' },
  open: { label: 'Open', tone: 'muted' },
  stale: { label: 'Decayed', tone: 'warn' },
  weak_artifact: { label: 'No artifact', tone: 'warn' },
  never_probed_cold: { label: 'Never probed cold', tone: 'muted' }
};

export function gateBadge(verdict: string): { label: string; tone: BadgeTone } {
  return BADGES[verdict] ?? { label: verdict, tone: 'muted' };
}
```

Run: `npx vitest run src/lib/programs.test.ts` — Expected: PASS.

- [ ] **Step 3: Add types and api calls**

Append to `frontend/src/lib/types.ts`:

```typescript
export interface Program {
  id: number; title: string; goal_statement: string; status: string; milestone_count: number;
}
export interface LinkInfo {
  id: number; status: string; proposed_title: string; why: string;
  sources: string[]; topic_id: number | null;
}
export interface MilestoneInfo {
  id: number; title: string; success_criteria: string; order_index: number;
  gate_status: string; depends_on: number[]; override_reason: string; links: LinkInfo[];
}
export interface ProgramDetail { program: Program; milestones: MilestoneInfo[]; }
export interface ConceptEvidence {
  concept_id: number; name: string; delayed_ok: boolean; artifact_ok: boolean; verdict: string;
}
export interface GateReport {
  milestone_id: number; verdict: string; reason: string; concepts: ConceptEvidence[];
}
export interface ProgramContext {
  program_id: number; program_title: string; milestone_id: number;
  milestone_title: string; gate_status: string; unverified: string[];
}
export interface CreateProgramBody {
  title: string; goal_statement?: string; target_depth?: string; prior_knowledge?: string;
  weekly_time_budget?: string; horizon?: string; focus_area?: string;
}
```

In `frontend/src/lib/api.ts`, add the new types to the type-import line and append inside the `api` object (matching the existing `fetch(...).then(j<T>)` style):

```typescript
  listPrograms: () => fetch('/api/programs').then(j<Program[]>),
  createProgram: (body: CreateProgramBody) =>
    fetch('/api/programs', {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }).then(j<Program>),
  getProgram: (id: number) => fetch(`/api/programs/${id}`).then(j<ProgramDetail>),
  programResearch: (id: number) =>
    fetch(`/api/programs/${id}/research`, { method: 'POST' }).then(j<ProgramDetail>),
  acceptProgram: (id: number, accepted_link_ids: number[], pruned_link_ids: number[]) =>
    fetch(`/api/programs/${id}/accept`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ accepted_link_ids, pruned_link_ids })
    }).then(j<ProgramDetail>),
  startLink: (pid: number, linkId: number) =>
    fetch(`/api/programs/${pid}/links/${linkId}/start`, { method: 'POST' }).then(j<{ topic_id: number }>),
  milestoneGate: (pid: number, mid: number) =>
    fetch(`/api/programs/${pid}/milestones/${mid}/gate`).then(j<GateReport>),
  overrideGate: (pid: number, mid: number, reason: string) =>
    fetch(`/api/programs/${pid}/milestones/${mid}/override`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ reason })
    }).then(j<MilestoneInfo>),
  updateMilestone: (pid: number, mid: number, body: Partial<Pick<MilestoneInfo, 'title' | 'success_criteria' | 'order_index' | 'depends_on'>>) =>
    fetch(`/api/programs/${pid}/milestones/${mid}`, {
      method: 'PUT',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body)
    }).then(j<MilestoneInfo>),
  programContext: (topicId: number) =>
    fetch(`/api/topics/${topicId}/program-context`).then((r) =>
      r.status === 404 ? null : j<ProgramContext>(r)
    ),
```

- [ ] **Step 4: Build the list + intake pages**

```svelte
<!-- frontend/src/routes/programs/+page.svelte -->
<script lang="ts">
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Program } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge } from '$lib/ui';

  let programs = $state<Program[]>([]);
  let loading = $state(true);
  onMount(async () => {
    programs = await api.listPrograms();
    loading = false;
  });
</script>

<svelte:head><title>Programs · Adaptive Academy</title></svelte:head>

<Page eyebrow="Voyages" title="Programs"
      lead="Long-horizon goals: researched milestone maps with verified-depth gates.">
  {#snippet actions()}
    <Button href="/programs/new">New program</Button>
  {/snippet}
  {#if loading}
    <p class="text-sm text-muted">Loading…</p>
  {:else if programs.length === 0}
    <Card>
      <p class="text-sm text-muted">
        No programs yet. A program owns a substantial goal — e.g. PhD-level CS prep —
        as a sequence of gated milestones, each spawning full topics when you start them.
      </p>
    </Card>
  {:else}
    <div class="grid gap-3">
      {#each programs as p (p.id)}
        <a href={`/programs/${p.id}`} class="block">
          <Card>
            <div class="flex items-center justify-between gap-3">
              <div class="min-w-0">
                <div class="text-fg">{p.title}</div>
                <div class="mt-1 truncate text-sm text-muted">{p.goal_statement}</div>
              </div>
              <Badge>{p.milestone_count} milestones</Badge>
            </div>
          </Card>
        </a>
      {/each}
    </div>
  {/if}
</Page>
```

```svelte
<!-- frontend/src/routes/programs/new/+page.svelte -->
<script lang="ts">
  import { goto } from '$app/navigation';
  import { api } from '$lib/api';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button } from '$lib/ui';

  let title = $state('');
  let goal_statement = $state('');
  let focus_area = $state('');
  let target_depth = $state('');
  let prior_knowledge = $state('');
  let weekly_time_budget = $state('');
  let horizon = $state('');
  let busy = $state(false);
  let error = $state('');

  async function submit() {
    if (!title.trim()) { error = 'Give the program a title.'; return; }
    busy = true; error = '';
    try {
      const p = await api.createProgram({
        title, goal_statement, focus_area, target_depth,
        prior_knowledge, weekly_time_budget, horizon
      });
      await goto(`/programs/${p.id}`);
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
      busy = false;
    }
  }
</script>

<svelte:head><title>New program · Adaptive Academy</title></svelte:head>

<Page eyebrow="Voyages" title="New program" width="narrow"
      lead="Describe the substantial goal. Research drafts a milestone map you review before anything is built.">
  <Card>
    <div class="grid gap-4">
      <label class="grid gap-1 text-sm">
        <span class="text-muted">Title</span>
        <input class="input" bind:value={title} placeholder="PhD-level CS prep — custom LLMs" />
      </label>
      <label class="grid gap-1 text-sm">
        <span class="text-muted">Goal statement — why deep, why this</span>
        <textarea class="input" rows="3" bind:value={goal_statement}
          placeholder="Research-ready: read frontier papers critically, reproduce results, extend one."></textarea>
      </label>
      <label class="grid gap-1 text-sm">
        <span class="text-muted">Focus area</span>
        <input class="input" bind:value={focus_area} placeholder="custom LLM models" />
      </label>
      <div class="grid grid-cols-2 gap-4">
        <label class="grid gap-1 text-sm">
          <span class="text-muted">Target depth</span>
          <input class="input" bind:value={target_depth} placeholder="PhD-level" />
        </label>
        <label class="grid gap-1 text-sm">
          <span class="text-muted">Horizon</span>
          <input class="input" bind:value={horizon} placeholder="2 years" />
        </label>
        <label class="grid gap-1 text-sm">
          <span class="text-muted">Weekly time budget</span>
          <input class="input" bind:value={weekly_time_budget} placeholder="10h/week" />
        </label>
        <label class="grid gap-1 text-sm">
          <span class="text-muted">Prior knowledge</span>
          <input class="input" bind:value={prior_knowledge} placeholder="MS DS, physics UG, 10y eng" />
        </label>
      </div>
      {#if error}<p class="text-sm text-danger">{error}</p>{/if}
      <div><Button onclick={submit} disabled={busy}>{busy ? 'Creating…' : 'Create program'}</Button></div>
    </div>
  </Card>
</Page>
```

Implementer note: match input styling to whatever `frontend/src/routes/topics/new/+page.svelte` uses (if there is no `.input` utility class, copy that page's input classes verbatim). Same for `Button href=` vs an `<a>` wrapper — mirror the existing pages' idiom.

- [ ] **Step 5: Add the nav entry**

In `frontend/src/lib/shell/Rail.svelte`, the `Voyages` section currently reads:

```typescript
    label: 'Voyages',
    items: [{ label: 'Fleet', icon: 'fleet', href: '/fleet', match: (p) => p === '/fleet' }]
```

Change to:

```typescript
    label: 'Voyages',
    items: [
      { label: 'Fleet', icon: 'fleet', href: '/fleet', match: (p) => p === '/fleet' },
      { label: 'Programs', icon: 'map', href: '/programs', match: (p) => p.startsWith('/programs') }
    ]
```

(`map` is an existing icon name in `Icon.svelte`; reuse it rather than adding an icon.)

- [ ] **Step 6: Verify**

Run: `cd frontend && npx vitest run && npx svelte-check && npm run build`
Expected: vitest green, svelte-check 0 errors, build succeeds.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/ frontend/src/routes/programs/
git commit -m "feat(program): /programs list + intake pages, api client, nav entry"
```

---

### Task 7: Frontend — `/programs/[id]` program map

**Files:**
- Create: `frontend/src/routes/programs/[id]/+page.svelte`

**Interfaces:**
- Consumes: Task 6 api calls + `gateBadge`.

Single page with three modes driven by data shape:
1. **No milestones yet** → "Run research" CTA (calls `api.programResearch`, then reloads).
2. **Proposal review** (any link `status === 'proposed'`) → editable milestone list (title + success criteria inline edit via `api.updateMilestone`), per-link keep/prune checkboxes, "Accept program" button (calls `api.acceptProgram` with kept vs pruned ids).
3. **Active program** → milestone rail in order, each showing: gate badge (`gateBadge(m.gate_status)`), success criteria, links with status chips, "Start topic" button on stubs (calls `api.startLink` then `goto('/topics/{topic_id}/review')`), lazy-loaded gate evidence table (`api.milestoneGate` on expand: concept rows × delayed ✓ / artifact ✓ / verdict badge), and an override affordance (reason `<textarea>` + confirm calling `api.overrideGate`; show `override_reason` when overridden).

- [ ] **Step 1: Implement the page**

```svelte
<!-- frontend/src/routes/programs/[id]/+page.svelte -->
<script lang="ts">
  import { page } from '$app/stores';
  import { goto } from '$app/navigation';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import { gateBadge } from '$lib/programs';
  import type { GateReport, MilestoneInfo, ProgramDetail } from '$lib/types';
  import Page from '$lib/shell/Page.svelte';
  import { Card, Button, Badge } from '$lib/ui';

  const programId = Number($page.params.id);
  let detail = $state<ProgramDetail | null>(null);
  let busy = $state(false);
  let error = $state('');
  let pruned = $state<Set<number>>(new Set());
  let gates = $state<Record<number, GateReport>>({});
  let overrideFor = $state<number | null>(null);
  let overrideReason = $state('');

  const inReview = $derived(
    detail?.milestones.some((m) => m.links.some((l) => l.status === 'proposed')) ?? false
  );

  async function load() {
    detail = await api.getProgram(programId);
  }
  onMount(load);

  async function runResearch() {
    busy = true; error = '';
    try { detail = await api.programResearch(programId); }
    catch (e) { error = e instanceof Error ? e.message : String(e); }
    busy = false;
  }

  function togglePrune(id: number) {
    const next = new Set(pruned);
    next.has(id) ? next.delete(id) : next.add(id);
    pruned = next;
  }

  async function accept() {
    if (!detail) return;
    busy = true; error = '';
    const all = detail.milestones.flatMap((m) => m.links.filter((l) => l.status === 'proposed'));
    const prunedIds = all.filter((l) => pruned.has(l.id)).map((l) => l.id);
    const keptIds = all.filter((l) => !pruned.has(l.id)).map((l) => l.id);
    try { detail = await api.acceptProgram(programId, keptIds, prunedIds); }
    catch (e) { error = e instanceof Error ? e.message : String(e); }
    busy = false;
  }

  async function start(linkId: number) {
    busy = true;
    try {
      const { topic_id } = await api.startLink(programId, linkId);
      await goto(`/topics/${topic_id}/review`);
    } catch (e) { error = e instanceof Error ? e.message : String(e); busy = false; }
  }

  async function loadGate(m: MilestoneInfo) {
    gates = { ...gates, [m.id]: await api.milestoneGate(programId, m.id) };
    await load(); // gate evaluation can update stored gate_status
  }

  async function confirmOverride(mid: number) {
    if (!overrideReason.trim()) { error = 'Override requires a reason.'; return; }
    busy = true; error = '';
    try {
      await api.overrideGate(programId, mid, overrideReason.trim());
      overrideFor = null; overrideReason = '';
      await load();
    } catch (e) { error = e instanceof Error ? e.message : String(e); }
    busy = false;
  }
</script>

<svelte:head><title>{detail?.program.title ?? 'Program'} · Adaptive Academy</title></svelte:head>

<Page eyebrow="Program" title={detail?.program.title ?? ''} width="wide"
      lead={detail?.program.goal_statement ?? ''}>
  {#if !detail}
    <p class="text-sm text-muted">Loading…</p>
  {:else if detail.milestones.length === 0}
    <Card>
      <p class="mb-4 text-sm text-muted">
        No milestone map yet. Research surveys real PhD curricula, quals syllabi, canonical
        courses, and reading lists, then drafts milestones + topic candidates for your review.
      </p>
      <Button onclick={runResearch} disabled={busy}>{busy ? 'Researching…' : 'Run research'}</Button>
      {#if error}<p class="mt-3 text-sm text-danger">{error}</p>{/if}
    </Card>
  {:else}
    {#if inReview}
      <Card>
        <div class="flex items-center justify-between gap-3">
          <p class="text-sm text-muted">
            Proposal under review — uncheck any candidate topic to prune it, then accept.
          </p>
          <Button onclick={accept} disabled={busy}>{busy ? 'Accepting…' : 'Accept program'}</Button>
        </div>
        {#if error}<p class="mt-2 text-sm text-danger">{error}</p>{/if}
      </Card>
    {/if}
    <div class="mt-4 grid gap-4">
      {#each detail.milestones as m, i (m.id)}
        <Card>
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <div class="eyebrow">Leg {i + 1}{m.depends_on.length ? ` · after ${m.depends_on.map((d) => `#${detail.milestones.findIndex((x) => x.id === d) + 1}`).join(', ')}` : ''}</div>
              <h2 class="mt-1 text-lg text-fg">{m.title}</h2>
              <p class="mt-1 text-sm text-muted">{m.success_criteria}</p>
              {#if m.gate_status === 'overridden' && m.override_reason}
                <p class="mt-1 text-xs text-muted">Override reason: {m.override_reason}</p>
              {/if}
            </div>
            <Badge>{gateBadge(m.gate_status).label}</Badge>
          </div>

          <ul class="mt-4 grid gap-2">
            {#each m.links as l (l.id)}
              <li class="flex items-center justify-between gap-3 text-sm">
                <div class="flex min-w-0 items-center gap-2">
                  {#if l.status === 'proposed'}
                    <input type="checkbox" checked={!pruned.has(l.id)}
                           onchange={() => togglePrune(l.id)} />
                  {/if}
                  <span class="truncate {l.status === 'pruned' ? 'line-through text-muted' : 'text-fg'}">
                    {l.proposed_title}</span>
                  {#if l.why}<span class="truncate text-muted">— {l.why}</span>{/if}
                </div>
                <div class="flex shrink-0 items-center gap-2">
                  {#if l.status === 'stub'}
                    <Button onclick={() => start(l.id)} disabled={busy}>Start topic</Button>
                  {:else if l.status === 'started' && l.topic_id}
                    <a class="text-accent hover:underline" href={`/topics/${l.topic_id}/today`}>Open topic</a>
                  {:else}
                    <Badge>{l.status}</Badge>
                  {/if}
                </div>
              </li>
            {/each}
          </ul>

          {#if !inReview}
            <div class="mt-4 flex items-center gap-3">
              <Button onclick={() => loadGate(m)}>Check gate</Button>
              {#if m.gate_status !== 'passed' && overrideFor !== m.id}
                <button class="text-sm text-muted hover:text-fg"
                        onclick={() => { overrideFor = m.id; overrideReason = ''; }}>
                  Override…</button>
              {/if}
            </div>
            {#if overrideFor === m.id}
              <div class="mt-3 grid gap-2">
                <textarea class="input" rows="2" bind:value={overrideReason}
                          placeholder="Why are you moving on without verification? (logged permanently)"></textarea>
                <div class="flex gap-2">
                  <Button onclick={() => confirmOverride(m.id)} disabled={busy}>Confirm override</Button>
                  <button class="text-sm text-muted" onclick={() => (overrideFor = null)}>Cancel</button>
                </div>
              </div>
            {/if}
            {#if gates[m.id]}
              <div class="mt-4 overflow-x-auto">
                <p class="mb-2 text-xs text-muted">{gates[m.id].reason}</p>
                {#if gates[m.id].concepts.length > 0}
                  <table class="w-full text-sm">
                    <thead>
                      <tr class="text-left text-xs text-muted">
                        <th class="py-1 pr-4 font-normal">Load-bearing concept</th>
                        <th class="py-1 pr-4 font-normal">Delayed recall</th>
                        <th class="py-1 pr-4 font-normal">Artifact</th>
                        <th class="py-1 font-normal">Verdict</th>
                      </tr>
                    </thead>
                    <tbody>
                      {#each gates[m.id].concepts as c (c.concept_id)}
                        <tr class="border-t border-border/50">
                          <td class="py-1.5 pr-4 text-fg">{c.name}</td>
                          <td class="py-1.5 pr-4">{c.delayed_ok ? '✓' : '—'}</td>
                          <td class="py-1.5 pr-4">{c.artifact_ok ? '✓' : '—'}</td>
                          <td class="py-1.5"><Badge>{gateBadge(c.verdict).label}</Badge></td>
                        </tr>
                      {/each}
                    </tbody>
                  </table>
                {/if}
              </div>
            {/if}
          {/if}
        </Card>
      {/each}
    </div>
  {/if}
</Page>
```

Implementer note: match `Badge`/`Button` prop APIs to their actual definitions in `frontend/src/lib/ui` (e.g. if `Badge` takes a `tone`/`variant` prop, pass `gateBadge(...).tone` through it; if `Button` has no `href` prop, wrap in `<a>`). Match the border/danger utility class names to those already used in neighboring pages.

- [ ] **Step 2: Verify**

Run: `cd frontend && npx svelte-check && npm run build`
Expected: 0 errors, build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/routes/programs/
git commit -m "feat(program): program map page — proposal review, milestone rail, gate evidence, override"
```

---

### Task 8: Frontend — Today program strip + Track breadcrumb

**Files:**
- Modify: `frontend/src/routes/topics/[id]/today/+page.svelte`
- Modify: `frontend/src/routes/topics/[id]/track/+page.svelte`

**Interfaces:**
- Consumes: `api.programContext(topicId)` (returns `ProgramContext | null`), `gateBadge`.

- [ ] **Step 1: Add the strip to Today**

In `frontend/src/routes/topics/[id]/today/+page.svelte`:

1. Add imports: `import { gateBadge } from '$lib/programs';` and add `ProgramContext` to the type imports.
2. Add state: `let programCtx = $state<ProgramContext | null>(null);`
3. In the existing `onMount` (or load function), add: `programCtx = await api.programContext(topicId);`
4. At the top of the rendered content (immediately inside `<Page>`, before the existing cards), add:

```svelte
  {#if programCtx}
    <Card>
      <div class="flex flex-wrap items-center justify-between gap-3">
        <div class="min-w-0 text-sm">
          <a class="text-accent hover:underline" href={`/programs/${programCtx.program_id}`}>
            {programCtx.program_title}</a>
          <span class="text-muted"> / {programCtx.milestone_title}</span>
        </div>
        <Badge>{gateBadge(programCtx.gate_status).label}</Badge>
      </div>
      {#if programCtx.unverified.length > 0}
        <p class="mt-2 text-sm text-muted">
          Gate needs cold verification of:
          <span class="text-fg">{programCtx.unverified.slice(0, 3).join(', ')}</span>
          {#if programCtx.unverified.length > 3}&nbsp;+{programCtx.unverified.length - 3} more{/if}
          — run a Decay Check or ship an artifact.
        </p>
      {/if}
    </Card>
  {/if}
```

- [ ] **Step 2: Add the breadcrumb to Track**

In `frontend/src/routes/topics/[id]/track/+page.svelte`: same import/state/fetch additions, then directly under the page header (or as the `eyebrow` line if the page uses `Page`'s `eyebrow` prop — prefer whichever slot exists) render:

```svelte
  {#if programCtx}
    <p class="mb-4 text-xs text-muted">
      Part of <a class="text-accent hover:underline" href={`/programs/${programCtx.program_id}`}>{programCtx.program_title}</a>
      / {programCtx.milestone_title}
    </p>
  {/if}
```

- [ ] **Step 3: Verify + commit**

Run: `cd frontend && npx svelte-check && npm run build` — Expected: clean.

```bash
git add frontend/src/routes/topics/
git commit -m "feat(program): Today program strip + Track breadcrumb"
```

---

### Task 9: Integration test + full verification

**Files:**
- Test: `tests/test_integration_program_loop.py`

**Interfaces:**
- Consumes: everything above. This is the program-scale analog of `tests/test_integration_loop.py`: create → research → accept → start → topic curriculum → alias carryover → evidence → gate.

- [ ] **Step 1: Write the integration test**

```python
# tests/test_integration_program_loop.py
"""Program-layer loop: intake → research → accept → start topic → curriculum with
alias carryover → evidence rows → gate verdict flips. Scripted LLM/researcher doubles;
LLM responses are queued IN CALL ORDER: program synthesis, topic foundation, topic
curriculum (×2 topics)."""
import json
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from sqlmodel import Session, select

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import Assessment, Concept, KnowledgeEstimate, Track

SYNTH = {"milestones": [
    {"title": "Foundations", "success_criteria": "derive backprop cold", "depends_on": [],
     "topics": [{"title": "Backprop", "why": "core"}]},
    {"title": "Architectures", "success_criteria": "transformer unaided", "depends_on": [0],
     "topics": [{"title": "Transformers", "why": "core"}]},
]}
FOUNDATION_1 = {"overview": "o", "key_concepts": ["Backprop", "Chain rule"],
                "prerequisite_map": {"Backprop": ["Chain rule"]}}
CURRICULUM_1 = {"overview": "o", "phases": [
    {"title": "P1", "items": [{"type": "build", "text": "implement backprop",
                               "concept_refs": ["Backprop"]}],
     "deliverable": {"kind": "repo", "text": "backprop from scratch"}},
    {"title": "P2", "items": [{"type": "write", "text": "explain chain rule",
                               "concept_refs": ["Chain rule"]}],
     "deliverable": {"kind": "blog", "text": "chain rule post"}},
]}
FOUNDATION_2 = {"overview": "o", "key_concepts": ["Attention", "Chain rule"],
                "prerequisite_map": {"Attention": ["Chain rule"]}}
CURRICULUM_2 = {"overview": "o", "phases": [
    {"title": "P1", "items": [{"type": "build", "text": "implement attention",
                               "concept_refs": ["Attention"]}],
     "deliverable": {"kind": "repo", "text": "attention from scratch"}},
    {"title": "P2", "items": [{"type": "write", "text": "revisit chain rule",
                               "concept_refs": ["Chain rule"]}],
     "deliverable": {"kind": "blog", "text": "post"}},
]}


def _client(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([
        LLMResponse(text=json.dumps(SYNTH)),
        LLMResponse(text=json.dumps(FOUNDATION_1)),
        LLMResponse(text=json.dumps(CURRICULUM_1)),
        LLMResponse(text=json.dumps(FOUNDATION_2)),
        LLMResponse(text=json.dumps(CURRICULUM_2)),
    ])
    src = [RawSource(title="s", url="https://e.com/1", tier=1, relevance=0.9, summary="s")]
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "phd_curricula": list(src), "foundational_papers": list(src),
    })
    return TestClient(app)


def _run_topic_pipeline(client, topic_id: int) -> None:
    assert client.post(f"/api/topics/{topic_id}/research").status_code == 200
    proposed = client.get(f"/api/topics/{topic_id}/sources?status=proposed").json()
    client.post(f"/api/topics/{topic_id}/sources/review",
                json={"accepted_ids": [s["id"] for s in proposed], "pruned_ids": []})
    assert client.post(f"/api/topics/{topic_id}/curriculum").status_code == 200


def test_program_loop_end_to_end(session):
    client = _client(session)
    pid = client.post("/api/programs", json={
        "title": "PhD prep", "goal_statement": "research-ready",
        "focus_area": "custom LLMs"}).json()["id"]
    client.post(f"/api/programs/{pid}/research")
    detail = client.get(f"/api/programs/{pid}").json()
    m1, m2 = detail["milestones"]
    all_links = [l for m in detail["milestones"] for l in m["links"]]
    client.post(f"/api/programs/{pid}/accept",
                json={"accepted_link_ids": [l["id"] for l in all_links], "pruned_link_ids": []})

    # ---- start topic 1, run its pipeline (foundation+curriculum use scripted LLM) ----
    t1 = client.post(f"/api/programs/{pid}/links/{m1['links'][0]['id']}/start").json()["topic_id"]
    _run_topic_pipeline(client, t1)

    # gate 1 open — load-bearing "Chain rule" has no evidence yet
    gate = client.get(f"/api/programs/{pid}/milestones/{m1['id']}/gate").json()
    assert gate["verdict"] == "open"
    names = {c["name"]: c["verdict"] for c in gate["concepts"]}
    assert names == {"Chain rule": "never_probed_cold"}

    # ---- inject evidence: artifact grade + delayed held recall ----
    chain1 = session.exec(
        select(Concept).join(Track).where(Track.topic_id == t1, Concept.name == "Chain rule")
    ).first()
    est = session.exec(select(KnowledgeEstimate)
                       .where(KnowledgeEstimate.concept_id == chain1.id)).first()
    est.level = "medium"  # learner actually knows it moderately
    session.add(est)
    t0 = datetime(2026, 7, 1)
    session.add(Assessment(concept_id=chain1.id, kind="teach", prompt="p", score=0.9,
                           created_at=t0))
    session.add(Assessment(concept_id=chain1.id, kind="recall", prompt="p", score=0.85,
                           created_at=t0 + timedelta(days=8)))
    session.commit()
    assert client.get(f"/api/programs/{pid}/milestones/{m1['id']}/gate").json()["verdict"] == "passed"

    # ---- start topic 2: alias carryover seeds "Chain rule" from topic 1 ----
    t2 = client.post(f"/api/programs/{pid}/links/{m2['links'][0]['id']}/start").json()["topic_id"]
    _run_topic_pipeline(client, t2)
    chain2 = session.exec(
        select(Concept).join(Track).where(Track.topic_id == t2, Concept.name == "Chain rule")
    ).first()
    est2 = session.exec(select(KnowledgeEstimate)
                        .where(KnowledgeEstimate.concept_id == chain2.id)).first()
    assert est2.level == "medium"  # seeded from topic 1, not the cold "high" default

    # gate 2 still open: carryover seeds the ESTIMATE, but gate evidence is per concept
    # row — topic 2's "Chain rule" has no assessments of its own yet (the honest reading)
    gate2 = client.get(f"/api/programs/{pid}/milestones/{m2['id']}/gate").json()
    assert gate2["verdict"] == "open"

    # program context for topic 2 names its milestone
    ctx = client.get(f"/api/topics/{t2}/program-context").json()
    assert ctx["milestone_title"] == "Architectures"
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_integration_program_loop.py -q`
Expected: 1 passed. Debug notes if it fails: (a) the scripted LLM payload ORDER must match call order — program synthesis, then per-topic foundation → curriculum; (b) topic research uses the `foundational_papers`… topic angles while program research uses `phd_curricula`… — both keyed in the one ScriptedResearcherClient; (c) `insert_spaced_revisits` may add revisit items but does not add concepts, so key_concepts drive the Concept rows.

- [ ] **Step 3: Full verification**

```bash
uv run pytest -q          # entire backend suite green
uv run ruff check .       # clean
cd frontend && npx vitest run && npx svelte-check && npm run build && cd ..
```

Expected: all green/clean. Also verify migration state: `uv run alembic upgrade head` exits 0.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration_program_loop.py
git commit -m "test(program): end-to-end program loop — research→accept→start→carryover→gate"
```

---

## Post-plan checklist (for the finishing session)

- Run the superpowers:verification-before-completion skill before claiming done.
- Live dogfood note: the program research fan-out is web-search-heavy — run it in `AA_LLM_BACKEND=agent_sdk` mode (subscription) to avoid burning API credits, per the Plan 8/9 lesson. Remember every past live failure came from too-small `max_tokens` on a new client path — program synthesis reuses the existing clients (8192), so no new client is introduced.
- Update `docs/OVERVIEW.md` / README nav if they enumerate pages (check; add `/programs` where the other pages are listed).
- Follow-up spec (not this plan): research-apprenticeship (paper-reading probes, reproduce-then-extend deliverables) plugging into the capstone milestone.
