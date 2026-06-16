# CurriculumDirector Implementation Plan (Plan 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate an editable, phased `Track` (Phase/Item/Deliverable/Sidebar) from a researched Topic's `TopicFoundation` + accepted `SourceDoc`s, materialize the foundation's concepts as `Concept` rows so the Tutor runs on a generated curriculum, and round-trip the Track to/from markdown.

**Architecture:** A pure markdown serialize/parse inverse pair (`engine/track_markdown.py`) over plain `*View` dataclasses; a single-LLM-call orchestrator (`engine/curriculum.py`) that parses JSON → `TrackView`, derives load-bearing concepts, **code-enforces** spaced revisits, persists Track/Phase/Item/Deliverable/Sidebar/Concept(+KnowledgeEstimate), and traces via `AgentEvent`. Mirrors `engine/research.py` exactly.

**Tech Stack:** Python 3.12 · uv · FastAPI · SQLModel/SQLite · Alembic (batch) · SvelteKit 5 / Tailwind 4 / vitest.

**Spec:** `docs/superpowers/specs/2026-06-15-curriculum-director.md`. Read §2 (decisions) before starting.

**Conventions (match existing code):** JSON columns use `sa_column=Column(JSON)`. Engine orchestrators take injected clients, persist, emit topic-scoped `AgentEvent`s, return a result dataclass, then refresh. Tests use the `session` fixture in `tests/conftest.py` and `ScriptedLLMClient`. Run backend tests with `uv run pytest`, lint with `uv run ruff check`.

---

### Task 1: Data model — Phase, Item, Deliverable, Sidebar + Track.overview

**Files:**
- Modify: `src/adaptive_academy/models.py`
- Test: `tests/test_curriculum_models.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_curriculum_models.py
from sqlmodel import Session, select

from adaptive_academy.models import (
    Deliverable, Item, Phase, Sidebar, Topic, Track,
)


def test_track_phase_item_deliverable_sidebar(session: Session):
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Core track", overview="intro prose")
    session.add(track)
    session.commit()

    phase = Phase(track_id=track.id, title="Build a GPT", position=0,
                  est_hours="Weeks 2-5", flags=["optional"])
    session.add(phase)
    session.commit()
    session.add(Item(phase_id=phase.id, text="Karpathy video", type="watch",
                     position=0, concept_refs=["self-attention"]))
    session.add(Deliverable(phase_id=phase.id, kind="repo", text="nanoGPT repo",
                            acceptance_criteria=["trains", "writeup"]))
    session.add(Sidebar(track_id=track.id, kind="math_refresh",
                        title="Math foundations", body="linear algebra", position=0))
    session.commit()

    session.refresh(track)
    session.refresh(phase)
    assert track.overview == "intro prose"
    assert track.phases[0].title == "Build a GPT"
    assert track.phases[0].flags == ["optional"]
    assert track.phases[0].items[0].concept_refs == ["self-attention"]
    assert track.phases[0].deliverable.acceptance_criteria == ["trains", "writeup"]
    assert track.sidebars[0].kind == "math_refresh"
    item = session.exec(select(Item)).one()
    assert item.status == "todo" and item.type == "watch"
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_curriculum_models.py -q`
Expected: ImportError (Phase/Item/Deliverable/Sidebar not defined).

- [ ] **Step 3: Add the models**

In `src/adaptive_academy/models.py`, add `overview` + relationships to `Track` (keep existing fields/relationship):

```python
class Track(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id")
    title: str
    overview: str = ""
    topic: Optional[Topic] = Relationship(back_populates="tracks")
    concepts: list["Concept"] = Relationship(back_populates="track")
    phases: list["Phase"] = Relationship(
        back_populates="track",
        sa_relationship_kwargs={"order_by": "Phase.position"},
    )
    sidebars: list["Sidebar"] = Relationship(
        back_populates="track",
        sa_relationship_kwargs={"order_by": "Sidebar.position"},
    )
```

Append the new tables (after `TopicFoundation`):

```python
class Phase(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    track_id: int = Field(foreign_key="track.id")
    title: str
    position: int = 0
    est_hours: str = ""
    flags: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    track: Optional[Track] = Relationship(back_populates="phases")
    items: list["Item"] = Relationship(
        back_populates="phase",
        sa_relationship_kwargs={"order_by": "Item.position"},
    )
    deliverable: Optional["Deliverable"] = Relationship(back_populates="phase")


class Item(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    phase_id: int = Field(foreign_key="phase.id")
    text: str
    type: str = "read"  # read | watch | build | write
    status: str = "todo"  # todo | doing | done
    position: int = 0
    links: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    source_doc_id: Optional[int] = Field(default=None, foreign_key="sourcedoc.id")
    concept_refs: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    phase: Optional[Phase] = Relationship(back_populates="items")


class Deliverable(SQLModel, table=True):
    """The per-phase '🎯 Ship' teaching artifact."""

    id: Optional[int] = Field(default=None, primary_key=True)
    phase_id: int = Field(foreign_key="phase.id", unique=True)
    kind: str = "blog"  # blog | repo | model | talk | ablation
    text: str
    acceptance_criteria: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    artifact_url: str = ""
    review_verdict: str = ""
    phase: Optional[Phase] = Relationship(back_populates="deliverable")


class Sidebar(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    track_id: int = Field(foreign_key="track.id")
    phase_id: Optional[int] = Field(default=None, foreign_key="phase.id")
    kind: str  # math_refresh | reading_list | reference
    title: str
    body: str = ""
    position: int = 0
    track: Optional[Track] = Relationship(back_populates="sidebars")
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_curriculum_models.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/models.py tests/test_curriculum_models.py
git commit -m "feat(models): Phase/Item/Deliverable/Sidebar + Track.overview"
```

---

### Task 2: Alembic migration for the curriculum tables

**Files:**
- Create: `alembic/versions/<rev>_curriculum_tables.py` (via autogenerate, then adjust)

- [ ] **Step 1: Autogenerate the migration**

Run: `uv run alembic revision --autogenerate -m "curriculum tables"`
This creates a new file under `alembic/versions/` with `down_revision = '58c3f587d8a0'`.

- [ ] **Step 2: Adjust the generated file to match this template**

Ensure `import sqlmodel` is present, the `track` alteration uses batch mode with a server default (so the seeded Track row is satisfied), and `item.source_doc_id` FK targets `sourcedoc`. The `upgrade()` / `downgrade()` bodies should be equivalent to:

```python
import sqlalchemy as sa
import sqlmodel
from alembic import op

def upgrade() -> None:
    op.create_table(
        "phase",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("est_hours", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("flags", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["track_id"], ["track.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "deliverable",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("acceptance_criteria", sa.JSON(), nullable=True),
        sa.Column("artifact_url", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("review_verdict", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.ForeignKeyConstraint(["phase_id"], ["phase.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phase_id"),
    )
    op.create_table(
        "item",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=False),
        sa.Column("text", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("type", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("status", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("links", sa.JSON(), nullable=True),
        sa.Column("source_doc_id", sa.Integer(), nullable=True),
        sa.Column("concept_refs", sa.JSON(), nullable=True),
        sa.ForeignKeyConstraint(["phase_id"], ["phase.id"]),
        sa.ForeignKeyConstraint(["source_doc_id"], ["sourcedoc.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "sidebar",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("track_id", sa.Integer(), nullable=False),
        sa.Column("phase_id", sa.Integer(), nullable=True),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("body", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["track_id"], ["track.id"]),
        sa.ForeignKeyConstraint(["phase_id"], ["phase.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("track", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("overview", sqlmodel.sql.sqltypes.AutoString(),
                      nullable=False, server_default=""))


def downgrade() -> None:
    with op.batch_alter_table("track", schema=None) as batch_op:
        batch_op.drop_column("overview")
    op.drop_table("sidebar")
    op.drop_table("item")
    op.drop_table("deliverable")
    op.drop_table("phase")
```

- [ ] **Step 3: Round-trip the migration**

Run:
```bash
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
```
Expected: no errors.

- [ ] **Step 4: Verify seed still works**

Run: `uv run python -c "from adaptive_academy.seed import seed; seed()"`
Expected: prints "Seeded ..." or "Already seeded." with no schema error.

- [ ] **Step 5: Commit**

```bash
git add alembic/versions/
git commit -m "feat(db): migration for curriculum tables + Track.overview"
```

---

### Task 3: `*View` dataclasses + `track_to_markdown`

**Files:**
- Create: `src/adaptive_academy/engine/track_markdown.py`
- Test: `tests/test_track_markdown.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_track_markdown.py
from adaptive_academy.engine.track_markdown import (
    DeliverableView, ItemView, PhaseView, SidebarView, TrackView,
    track_to_markdown,
)


def _sample() -> TrackView:
    return TrackView(
        title="Build LLMs from scratch",
        overview="A first-principles path.",
        phases=[
            PhaseView(
                title="Build a GPT by hand",
                est_hours="Weeks 2-5",
                flags=["optional"],
                items=[
                    ItemView(text="Karpathy: Let's build GPT", type="watch", status="done"),
                    ItemView(text="Train a char-level GPT", type="build", status="doing"),
                ],
                deliverable=DeliverableView(
                    text="nanoGPT-equivalent repo", kind="repo",
                    acceptance_criteria=["trains end to end", "has a writeup"]),
            ),
        ],
        sidebars=[SidebarView(kind="math_refresh", title="Math foundations",
                              body="linear algebra, chain rule")],
    )


def test_track_to_markdown_golden_format():
    md = track_to_markdown(_sample())
    assert "# Build LLMs from scratch" in md
    assert "## Phase 1 — Build a GPT by hand (Weeks 2-5) · _optional_" in md
    assert "- [x] (watch) Karpathy: Let's build GPT" in md
    assert "- [-] (build) Train a char-level GPT" in md
    assert "- **🎯 Ship:** (repo) nanoGPT-equivalent repo" in md
    assert "  - acceptance: trains end to end" in md
    assert "## Sidebar: Math foundations" in md
    assert "_kind: math_refresh_" in md
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_track_markdown.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement the dataclasses + serializer**

```python
# src/adaptive_academy/engine/track_markdown.py
from dataclasses import dataclass, field

_STATUS_TO_BOX = {"todo": " ", "doing": "-", "done": "x"}
_BOX_TO_STATUS = {v: k for k, v in _STATUS_TO_BOX.items()}


@dataclass
class ItemView:
    text: str
    type: str = "read"
    status: str = "todo"
    concept_refs: list[str] = field(default_factory=list)  # DB-only; not serialized


@dataclass
class DeliverableView:
    text: str
    kind: str = "blog"
    acceptance_criteria: list[str] = field(default_factory=list)


@dataclass
class SidebarView:
    kind: str
    title: str
    body: str = ""


@dataclass
class PhaseView:
    title: str
    est_hours: str = ""
    flags: list[str] = field(default_factory=list)
    items: list[ItemView] = field(default_factory=list)
    deliverable: "DeliverableView | None" = None


@dataclass
class TrackView:
    title: str
    overview: str = ""
    phases: list[PhaseView] = field(default_factory=list)
    sidebars: list[SidebarView] = field(default_factory=list)


def track_to_markdown(track: TrackView) -> str:
    """Serialize a TrackView to canonical markdown (the round-trip source of truth)."""
    lines: list[str] = [f"# {track.title}", ""]
    if track.overview:
        lines += [track.overview, ""]

    for i, p in enumerate(track.phases):
        header = f"## Phase {i + 1} — {p.title}"
        if p.est_hours:
            header += f" ({p.est_hours})"
        for fl in p.flags:
            header += f" · _{fl}_"
        lines.append(header)
        for it in p.items:
            box = _STATUS_TO_BOX.get(it.status, " ")
            lines.append(f"- [{box}] ({it.type}) {it.text}")
        if p.deliverable:
            d = p.deliverable
            lines.append(f"- **🎯 Ship:** ({d.kind}) {d.text}")
            for c in d.acceptance_criteria:
                lines.append(f"  - acceptance: {c}")
        lines.append("")

    for s in track.sidebars:
        lines.append(f"## Sidebar: {s.title}")
        lines.append(f"_kind: {s.kind}_")
        lines.append("")
        if s.body:
            lines += [s.body, ""]

    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_track_markdown.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/track_markdown.py tests/test_track_markdown.py
git commit -m "feat(engine): TrackView dataclasses + track_to_markdown"
```

---

### Task 4: `markdown_to_track` (exact inverse) + round-trip test

**Files:**
- Modify: `src/adaptive_academy/engine/track_markdown.py`
- Modify: `tests/test_track_markdown.py`

- [ ] **Step 1: Write the failing round-trip test**

Add to `tests/test_track_markdown.py`:

```python
from adaptive_academy.engine.track_markdown import markdown_to_track


def test_markdown_round_trip_equality():
    original = _sample()
    restored = markdown_to_track(track_to_markdown(original))
    assert restored == original


def test_round_trip_empty_and_multi_phase():
    tv = TrackView(
        title="T", overview="",
        phases=[
            PhaseView(title="P1", items=[ItemView(text="a", type="read")]),
            PhaseView(title="P2", est_hours="1h", flags=["stretch", "parallel_track"],
                      items=[], deliverable=DeliverableView(text="d", kind="blog")),
        ],
        sidebars=[],
    )
    assert markdown_to_track(track_to_markdown(tv)) == tv
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_track_markdown.py -q`
Expected: ImportError on `markdown_to_track`.

- [ ] **Step 3: Implement the parser (exact inverse)**

Append to `src/adaptive_academy/engine/track_markdown.py`:

```python
import re

_PHASE_RE = re.compile(r"^Phase \d+ — (?P<rest>.*)$")
_FLAG_RE = re.compile(r" · _(\w+)_")
_EST_RE = re.compile(r" \(([^)]*)\)$")
_ITEM_RE = re.compile(r"^- \[(?P<box>.)\] \((?P<type>\w+)\) (?P<text>.*)$")
_SHIP_RE = re.compile(r"^- \*\*🎯 Ship:\*\* \((?P<kind>\w+)\) (?P<text>.*)$")
_ACCEPT_PREFIX = "  - acceptance: "
_SIDEBAR_PREFIX = "## Sidebar: "
_KIND_RE = re.compile(r"^_kind: (?P<kind>\w+)_$")


def _parse_phase_header(rest: str) -> tuple[str, str, list[str]]:
    flags = _FLAG_RE.findall(rest)
    rest = _FLAG_RE.sub("", rest)
    est = ""
    m = _EST_RE.search(rest)
    if m:
        est = m.group(1)
        rest = rest[: m.start()]
    return rest.strip(), est, flags


def markdown_to_track(md: str) -> TrackView:
    """Parse markdown produced by track_to_markdown back into a TrackView."""
    lines = md.splitlines()
    title = ""
    overview_lines: list[str] = []
    phases: list[PhaseView] = []
    sidebars: list[SidebarView] = []

    i, n = 0, len(lines)
    # Title.
    while i < n and not lines[i].startswith("# "):
        i += 1
    if i < n:
        title = lines[i][2:].strip()
        i += 1
    # Overview: everything up to the first "## ".
    while i < n and not lines[i].startswith("## "):
        if lines[i].strip():
            overview_lines.append(lines[i])
        i += 1

    cur_phase: PhaseView | None = None
    cur_sidebar: SidebarView | None = None
    sidebar_body: list[str] = []

    def flush_sidebar() -> None:
        nonlocal cur_sidebar, sidebar_body
        if cur_sidebar is not None:
            cur_sidebar.body = "\n".join(sidebar_body).strip()
            sidebars.append(cur_sidebar)
        cur_sidebar, sidebar_body = None, []

    while i < n:
        line = lines[i]
        if line.startswith(_SIDEBAR_PREFIX):
            flush_sidebar()
            cur_phase = None
            cur_sidebar = SidebarView(kind="", title=line[len(_SIDEBAR_PREFIX):].strip())
            i += 1
            if i < n and (m := _KIND_RE.match(lines[i].strip())):
                cur_sidebar.kind = m.group("kind")
                i += 1
            continue
        if line.startswith("## "):
            flush_sidebar()
            m = _PHASE_RE.match(line[3:])
            ptitle, est, flags = _parse_phase_header(m.group("rest")) if m else (line[3:].strip(), "", [])
            cur_phase = PhaseView(title=ptitle, est_hours=est, flags=flags)
            phases.append(cur_phase)
            i += 1
            continue
        if cur_sidebar is not None:
            sidebar_body.append(line)
            i += 1
            continue
        if cur_phase is not None:
            if m := _ITEM_RE.match(line):
                cur_phase.items.append(ItemView(
                    text=m.group("text"), type=m.group("type"),
                    status=_BOX_TO_STATUS.get(m.group("box"), "todo")))
            elif m := _SHIP_RE.match(line):
                cur_phase.deliverable = DeliverableView(
                    text=m.group("text"), kind=m.group("kind"))
            elif line.startswith(_ACCEPT_PREFIX) and cur_phase.deliverable is not None:
                cur_phase.deliverable.acceptance_criteria.append(line[len(_ACCEPT_PREFIX):])
        i += 1

    flush_sidebar()
    return TrackView(title=title, overview="\n".join(overview_lines).strip(),
                     phases=phases, sidebars=sidebars)
```

Move the `import re` to the top of the file with the other import-level code (keep imports at module top).

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `uv run pytest tests/test_track_markdown.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/track_markdown.py tests/test_track_markdown.py
git commit -m "feat(engine): markdown_to_track inverse + round-trip tests"
```

---

### Task 5: `load_bearing_concepts` (derive from prerequisite map)

**Files:**
- Create: `src/adaptive_academy/engine/curriculum.py`
- Test: `tests/test_curriculum_concepts.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_curriculum_concepts.py
from adaptive_academy.engine.curriculum import load_bearing_concepts


def test_load_bearing_is_anything_depended_upon():
    prereq = {
        "self-attention": ["linear algebra", "softmax"],
        "backprop": ["calculus", "linear algebra"],
        "LoRA": ["linear algebra"],
    }
    lb = load_bearing_concepts(prereq)
    assert lb == {"linear algebra", "softmax", "calculus"}


def test_load_bearing_empty():
    assert load_bearing_concepts({}) == set()
    assert load_bearing_concepts({"a": []}) == set()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_curriculum_concepts.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement**

```python
# src/adaptive_academy/engine/curriculum.py
def load_bearing_concepts(prerequisite_map: dict) -> set[str]:
    """A concept is load-bearing iff something depends on it (it appears as a
    prerequisite in any value list). This is the signal the spaced-revisit pass keys on.
    """
    lb: set[str] = set()
    for prereqs in prerequisite_map.values():
        for name in prereqs or []:
            if isinstance(name, str) and name:
                lb.add(name)
    return lb
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_curriculum_concepts.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/curriculum.py tests/test_curriculum_concepts.py
git commit -m "feat(engine): load_bearing_concepts from prerequisite map"
```

---

### Task 6: `insert_spaced_revisits` (code-enforced spacing)

**Files:**
- Modify: `src/adaptive_academy/engine/curriculum.py`
- Test: `tests/test_curriculum_spacing.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_curriculum_spacing.py
from adaptive_academy.engine.curriculum import insert_spaced_revisits
from adaptive_academy.engine.track_markdown import ItemView, PhaseView


def _phases():
    return [
        PhaseView(title="P1", items=[ItemView(text="learn attention", type="read",
                                              concept_refs=["self-attention", "softmax"])]),
        PhaseView(title="P2", items=[ItemView(text="build gpt", type="build",
                                              concept_refs=["self-attention"])]),
        PhaseView(title="P3", items=[ItemView(text="pretrain", type="build",
                                              concept_refs=[])]),
    ]


def test_concept_in_one_phase_gets_a_later_revisit():
    phases = insert_spaced_revisits(_phases(), {"softmax"})
    # softmax only in P1 -> a revisit item referencing it is injected into a later phase
    later = [p for p in phases[1:] if any("softmax" in it.concept_refs for it in p.items)]
    assert later, "expected a spaced revisit of softmax in a later phase"
    injected = [it for p in phases for it in p.items if it.text.startswith("Revisit")]
    assert any("softmax" in it.concept_refs and it.type == "write" for it in injected)


def test_already_spaced_concept_is_left_alone():
    before = _phases()
    after = insert_spaced_revisits(before, {"self-attention"})
    # self-attention already appears in P1 and P2 -> no injection
    injected = [it for p in after for it in p.items if it.text.startswith("Revisit")]
    assert injected == []


def test_unreferenced_concept_is_touched_then_no_crash_single_phase():
    one = [PhaseView(title="only", items=[ItemView(text="x", concept_refs=[])])]
    out = insert_spaced_revisits(one, {"ghost"})
    # single phase: cannot space, but should not crash and should touch it once
    refs = [c for p in out for it in p.items for c in it.concept_refs]
    assert "ghost" in refs
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_curriculum_spacing.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement**

Append to `src/adaptive_academy/engine/curriculum.py`:

```python
from adaptive_academy.engine.track_markdown import ItemView, PhaseView


def _phases_referencing(phases: list[PhaseView], concept: str) -> list[int]:
    return [i for i, p in enumerate(phases)
            if any(concept in it.concept_refs for it in p.items)]


def _revisit_item(concept: str) -> ItemView:
    return ItemView(text=f"Revisit & self-explain: {concept}", type="write",
                    concept_refs=[concept])


def insert_spaced_revisits(phases: list[PhaseView], load_bearing: set[str]) -> list[PhaseView]:
    """Guarantee every load-bearing concept is revisited across phases (code-enforced).

    - referenced in >=2 phases -> already spaced, no-op
    - referenced in exactly 1 phase p -> inject a 'revisit' write-item into the
      earliest later phase that doesn't already reference it
    - referenced in 0 phases -> inject a touch into the last phase
    - single phase total -> can't space; ensure at least one touch in that phase
    """
    for concept in sorted(load_bearing):
        refs = _phases_referencing(phases, concept)
        if len(refs) >= 2:
            continue
        if not phases:
            break
        if len(refs) == 1:
            p = refs[0]
            target = next((j for j in range(p + 1, len(phases))), None)
            if target is None:
                continue  # only earlier/this phase exists; cannot space
            phases[target].items.append(_revisit_item(concept))
        else:  # 0 references
            phases[-1].items.append(_revisit_item(concept))
    return phases
```

- [ ] **Step 4: Run the tests to confirm they pass**

Run: `uv run pytest tests/test_curriculum_spacing.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/curriculum.py tests/test_curriculum_spacing.py
git commit -m "feat(engine): code-enforced insert_spaced_revisits pass"
```

---

### Task 7: `parse_curriculum_json` (LLM JSON → TrackView)

**Files:**
- Modify: `src/adaptive_academy/engine/curriculum.py`
- Test: `tests/test_curriculum_parse.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_curriculum_parse.py
import json

from adaptive_academy.engine.curriculum import parse_curriculum_json


def test_parses_full_payload():
    payload = json.dumps({
        "overview": "ov",
        "phases": [{
            "title": "P1", "est_hours": "Weeks 1-2", "flags": ["optional"],
            "items": [{"type": "read", "text": "paper", "concept_refs": ["x"]}],
            "deliverable": {"kind": "blog", "text": "post", "acceptance_criteria": ["clear"]},
        }],
        "sidebars": [{"kind": "math_refresh", "title": "Math", "body": "la"}],
    })
    tv = parse_curriculum_json(payload, title="Topic T")
    assert tv.title == "Topic T"
    assert tv.overview == "ov"
    assert tv.phases[0].flags == ["optional"]
    assert tv.phases[0].items[0].concept_refs == ["x"]
    assert tv.phases[0].deliverable.kind == "blog"
    assert tv.sidebars[0].kind == "math_refresh"


def test_strips_code_fences_and_defaults():
    tv = parse_curriculum_json('```json\n{"phases": [{"title": "P"}]}\n```', title="T")
    assert tv.phases[0].title == "P"
    assert tv.phases[0].items == [] and tv.phases[0].deliverable is None
    assert tv.overview == "" and tv.sidebars == []
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_curriculum_parse.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement (mirror `_parse_foundation_json`)**

Append to `src/adaptive_academy/engine/curriculum.py` (add `import json` at top):

```python
from adaptive_academy.engine.track_markdown import DeliverableView, SidebarView, TrackView


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def parse_curriculum_json(text: str, title: str) -> TrackView:
    data = json.loads(_strip_fences(text))
    phases: list[PhaseView] = []
    for p in data.get("phases", []) or []:
        items = [
            ItemView(text=str(it.get("text", "")), type=str(it.get("type", "read")),
                     concept_refs=list(it.get("concept_refs", []) or []))
            for it in (p.get("items", []) or [])
        ]
        d = p.get("deliverable") or None
        deliverable = None
        if d:
            deliverable = DeliverableView(
                text=str(d.get("text", "")), kind=str(d.get("kind", "blog")),
                acceptance_criteria=list(d.get("acceptance_criteria", []) or []))
        phases.append(PhaseView(
            title=str(p.get("title", "")), est_hours=str(p.get("est_hours", "")),
            flags=list(p.get("flags", []) or []), items=items, deliverable=deliverable))
    sidebars = [
        SidebarView(kind=str(s.get("kind", "reference")), title=str(s.get("title", "")),
                    body=str(s.get("body", "")))
        for s in (data.get("sidebars", []) or [])
    ]
    return TrackView(title=title, overview=str(data.get("overview", "")),
                     phases=phases, sidebars=sidebars)
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_curriculum_parse.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/curriculum.py tests/test_curriculum_parse.py
git commit -m "feat(engine): parse_curriculum_json -> TrackView"
```

---

### Task 8: `build_curriculum_prompt` (evidence-encoded)

**Files:**
- Modify: `src/adaptive_academy/engine/curriculum.py`
- Test: `tests/test_curriculum_prompt.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_curriculum_prompt.py
from adaptive_academy.engine.curriculum import build_curriculum_prompt
from adaptive_academy.models import SourceDoc, TopicFoundation, TopicIntent


def test_prompt_encodes_evidence_rules_and_context():
    intent = TopicIntent(topic_id=1, goal="build a GPT", prior_knowledge="strong eng",
                         time_budget="10h/wk")
    fnd = TopicFoundation(topic_id=1, overview="ov",
                          key_concepts=["self-attention", "backprop"],
                          prerequisite_map={"self-attention": ["linear algebra"]})
    sources = [SourceDoc(topic_id=1, title="Attention paper", url="u", tier=1,
                         summary="seminal", status="accepted")]
    system, user = build_curriculum_prompt("Build LLMs", intent, fnd, sources)
    low = system.lower()
    assert "low-assistance" in low or "low assistance" in low
    assert "🎯" in system or "ship" in low
    assert "json" in low
    assert "self-attention" in user and "Attention paper" in user
    assert "10h/wk" in user and "build a GPT" in user
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_curriculum_prompt.py -q`
Expected: ImportError.

- [ ] **Step 3: Implement**

Append to `src/adaptive_academy/engine/curriculum.py` (add the imports you need at top):

```python
from adaptive_academy.models import SourceDoc, TopicFoundation, TopicIntent

_CURRICULUM_SYSTEM = (
    "You are a CurriculumDirector for an ADVANCED, self-directed adult learner. "
    "Design an editable, phased learning Track from the foundation and reading list. "
    "Evidence-driven rules (follow them):\n"
    "- Default to LOW-ASSISTANCE, PROJECT/PROBLEM-FIRST items (expertise-reversal effect: "
    "high guidance harms experts). Lead with building/shipping, not lectures.\n"
    "- Give EXACTLY ONE shippable teaching artifact ('🎯 Ship') per phase "
    "(learning-by-teaching): a blog/repo/model/talk/ablation with acceptance criteria.\n"
    "- Revisit load-bearing prerequisites across LATER phases (spaced, not massed).\n"
    "- Treat deliberate-practice drills as SUPPORTING, never the spine.\n"
    "Respond with ONLY a JSON object: {\"overview\": str, \"phases\": [{\"title\": str, "
    "\"est_hours\": str, \"flags\": [\"optional\"|\"stretch\"|\"parallel_track\"], "
    "\"items\": [{\"type\": \"read\"|\"watch\"|\"build\"|\"write\", \"text\": str, "
    "\"concept_refs\": [str]}], \"deliverable\": {\"kind\": "
    "\"blog\"|\"repo\"|\"model\"|\"talk\"|\"ablation\", \"text\": str, "
    "\"acceptance_criteria\": [str]}}], \"sidebars\": [{\"kind\": "
    "\"math_refresh\"|\"reading_list\"|\"reference\", \"title\": str, \"body\": str}]}. "
    "Use the foundation's key concepts as item concept_refs. No prose outside the JSON."
)


def build_curriculum_prompt(
    topic_title: str, intent: TopicIntent, foundation: TopicFoundation,
    sources: list[SourceDoc],
) -> tuple[str, str]:
    lines = [
        f"TOPIC: {topic_title}",
        f"GOAL: {intent.goal}",
        f"PRIOR KNOWLEDGE: {intent.prior_knowledge}",
        f"TIME BUDGET: {intent.time_budget}",
        "",
        f"FOUNDATION OVERVIEW: {foundation.overview}",
        f"KEY CONCEPTS: {', '.join(foundation.key_concepts)}",
        f"PREREQUISITE MAP: {foundation.prerequisite_map}",
        "",
        "ACCEPTED READING LIST:",
    ]
    for s in sources:
        lines.append(f"- [{s.tier}] {s.title} ({s.url}) — {s.summary}".rstrip(" —"))
    return _CURRICULUM_SYSTEM, "\n".join(lines)
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_curriculum_prompt.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/engine/curriculum.py tests/test_curriculum_prompt.py
git commit -m "feat(engine): build_curriculum_prompt with evidence rules"
```

---

### Task 9: `generate_curriculum` orchestrator (persist + trace)

**Files:**
- Modify: `src/adaptive_academy/engine/curriculum.py`
- Test: `tests/test_curriculum_orchestrator.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_curriculum_orchestrator.py
import json

from sqlmodel import Session, select

from adaptive_academy.engine.curriculum import CurriculumResult, generate_curriculum
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent, Concept, Deliverable, Item, KnowledgeEstimate, Phase, Sidebar,
    SourceDoc, Topic, TopicFoundation, TopicIntent, Track,
)


def _setup(session: Session):
    topic = Topic(title="Build LLMs from scratch")
    session.add(topic)
    session.commit()
    intent = TopicIntent(topic_id=topic.id, goal="build a GPT",
                         prior_knowledge="strong", time_budget="10h/wk")
    fnd = TopicFoundation(topic_id=topic.id, overview="ov",
                          key_concepts=["self-attention", "linear algebra"],
                          prerequisite_map={"self-attention": ["linear algebra"]})
    src = SourceDoc(topic_id=topic.id, title="Attention", url="u", tier=1,
                    summary="s", status="accepted", rank=0)
    session.add_all([intent, fnd, src])
    session.commit()
    return topic, intent, fnd, [src]


def _llm() -> ScriptedLLMClient:
    payload = json.dumps({
        "overview": "a path",
        "phases": [
            {"title": "Foundations", "est_hours": "Wk1",
             "items": [{"type": "read", "text": "la refresher",
                        "concept_refs": ["linear algebra"]}],
             "deliverable": {"kind": "blog", "text": "notes",
                             "acceptance_criteria": ["clear"]}},
            {"title": "Build", "est_hours": "Wk2-5",
             "items": [{"type": "build", "text": "nanoGPT",
                        "concept_refs": ["self-attention"]}],
             "deliverable": {"kind": "repo", "text": "repo",
                             "acceptance_criteria": ["trains"]}},
        ],
        "sidebars": [{"kind": "math_refresh", "title": "Math", "body": "la"}],
    })
    return ScriptedLLMClient([LLMResponse(text=payload)])


def test_generate_persists_full_track_and_traces(session: Session):
    topic, intent, fnd, sources = _setup(session)
    result = generate_curriculum(session, topic, intent, fnd, sources, llm=_llm())
    assert isinstance(result, CurriculumResult)

    track = session.exec(select(Track).where(Track.topic_id == topic.id)).one()
    assert track.overview == "a path"
    phases = session.exec(select(Phase).where(Phase.track_id == track.id)).all()
    assert len(phases) == 2
    assert [p.position for p in sorted(phases, key=lambda x: x.position)] == [0, 1]
    assert session.exec(select(Deliverable)).all() and session.exec(select(Item)).all()
    assert session.exec(select(Sidebar)).all()

    # Concepts materialized with load-bearing flags + seeded estimates
    concepts = session.exec(select(Concept).where(Concept.track_id == track.id)).all()
    by_name = {c.name: c for c in concepts}
    assert by_name["linear algebra"].is_load_bearing is True   # depended upon
    assert by_name["self-attention"].is_load_bearing is False
    estimates = session.exec(select(KnowledgeEstimate)).all()
    assert len(estimates) == len(concepts) and all(e.level == "high" for e in estimates)

    # Spaced revisit: linear algebra referenced only in P1 -> injected into a later phase
    items = session.exec(select(Item)).all()
    revisit = [it for it in items if it.text.startswith("Revisit")]
    assert any("linear algebra" in it.concept_refs for it in revisit)

    # Trace: topic-scoped events, one per step incl. done
    events = session.exec(select(AgentEvent).where(AgentEvent.topic_id == topic.id)).all()
    kinds = {e.kind for e in events}
    assert {"curriculum:plan", "curriculum:generated", "curriculum:concepts",
            "curriculum:done"}.issubset(kinds)
    assert all(e.conversation_id is None for e in events)
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_curriculum_orchestrator.py -q`
Expected: ImportError on `generate_curriculum` / `CurriculumResult`.

- [ ] **Step 3: Implement the orchestrator**

Append to `src/adaptive_academy/engine/curriculum.py` (add imports: `dataclass`, `Session`, `LLMClient`, models `AgentEvent, Concept, Deliverable, Item, KnowledgeEstimate, Phase, Sidebar, Topic, Track`):

```python
from dataclasses import dataclass

from sqlmodel import Session

from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent, Concept, Deliverable, Item, KnowledgeEstimate, Phase, Sidebar,
    Topic, Track,
)


@dataclass
class CurriculumResult:
    track: Track
    events: list[AgentEvent]


def generate_curriculum(
    session: Session,
    topic: Topic,
    intent: TopicIntent,
    foundation: TopicFoundation,
    sources: list[SourceDoc],
    *,
    llm: LLMClient,
) -> CurriculumResult:
    """Single LLM call -> TrackView; enforce spacing; persist Track/Phase/Item/
    Deliverable/Sidebar/Concept(+estimate); trace; return."""
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    emit("curriculum:plan", f"{len(foundation.key_concepts)} concepts, {len(sources)} sources")
    system, user = build_curriculum_prompt(topic.title, intent, foundation, sources)
    resp = llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[])
    draft = parse_curriculum_json(resp.text, title=topic.title)

    lb = load_bearing_concepts(foundation.prerequisite_map)
    before = sum(len(p.items) for p in draft.phases)
    insert_spaced_revisits(draft.phases, lb)
    revisits = sum(len(p.items) for p in draft.phases) - before
    emit("curriculum:generated", f"{len(draft.phases)} phases")
    if revisits:
        emit("curriculum:spaced", f"{revisits} revisit item(s) injected")

    track = Track(topic_id=topic.id, title=topic.title, overview=draft.overview)
    session.add(track)
    session.commit()
    session.refresh(track)

    for pi, pv in enumerate(draft.phases):
        phase = Phase(track_id=track.id, title=pv.title, position=pi,
                      est_hours=pv.est_hours, flags=pv.flags)
        session.add(phase)
        session.commit()
        session.refresh(phase)
        for ii, iv in enumerate(pv.items):
            session.add(Item(phase_id=phase.id, text=iv.text, type=iv.type,
                             position=ii, concept_refs=iv.concept_refs))
        if pv.deliverable:
            session.add(Deliverable(phase_id=phase.id, kind=pv.deliverable.kind,
                                    text=pv.deliverable.text,
                                    acceptance_criteria=pv.deliverable.acceptance_criteria))
    for si, sv in enumerate(draft.sidebars):
        session.add(Sidebar(track_id=track.id, kind=sv.kind, title=sv.title,
                            body=sv.body, position=si))

    lb_count = 0
    for name in foundation.key_concepts:
        is_lb = name in lb
        lb_count += int(is_lb)
        concept = Concept(track_id=track.id, name=name, is_load_bearing=is_lb)
        session.add(concept)
        session.commit()
        session.refresh(concept)
        session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.5))
    emit("curriculum:concepts", f"{len(foundation.key_concepts)} concepts, {lb_count} load-bearing")

    emit("curriculum:done", f"track {track.id}")
    session.commit()
    session.refresh(track)
    return CurriculumResult(track=track, events=events)
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_curriculum_orchestrator.py -q`
Expected: PASS.

- [ ] **Step 5: Run the full engine suite + lint**

Run: `uv run pytest tests/ -q && uv run ruff check src tests`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add src/adaptive_academy/engine/curriculum.py tests/test_curriculum_orchestrator.py
git commit -m "feat(engine): generate_curriculum orchestrator (persist + trace)"
```

---

### Task 10: API schemas for curriculum

**Files:**
- Modify: `src/adaptive_academy/api/schemas.py`

- [ ] **Step 1: Add the schemas**

Append to `src/adaptive_academy/api/schemas.py` and extend `TopicOut`:

```python
class ItemOut(BaseModel):
    id: int
    text: str
    type: str
    status: str
    position: int


class DeliverableOut(BaseModel):
    id: int
    kind: str
    text: str
    acceptance_criteria: list[str]


class SidebarOut(BaseModel):
    id: int
    kind: str
    title: str
    body: str
    position: int


class PhaseOut(BaseModel):
    id: int
    title: str
    position: int
    est_hours: str
    flags: list[str]
    items: list[ItemOut]
    deliverable: Optional[DeliverableOut] = None


class TrackOut(BaseModel):
    id: int
    title: str
    overview: str


class CurriculumOut(BaseModel):
    track: TrackOut
    phases: list[PhaseOut]
    sidebars: list[SidebarOut]
    concepts: list[ConceptOut]
    events: list[EventOut] = []


class ImportMarkdownIn(BaseModel):
    markdown: str


class ItemPatchIn(BaseModel):
    status: Optional[str] = None
    text: Optional[str] = None
```

Add `has_track: bool = False` to `TopicOut`:

```python
class TopicOut(BaseModel):
    id: int
    title: str
    concepts: list[ConceptOut]
    intent: Optional[IntentOut] = None
    has_foundation: bool = False
    has_track: bool = False
```

- [ ] **Step 2: Verify import**

Run: `uv run python -c "import adaptive_academy.api.schemas"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add src/adaptive_academy/api/schemas.py
git commit -m "feat(api): curriculum schemas (Track/Phase/Item/Deliverable/Sidebar)"
```

---

### Task 11: Curriculum routes (generate / get / export / import) + serializer

**Files:**
- Modify: `src/adaptive_academy/api/routes_topics.py`
- Test: `tests/test_api_curriculum.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_curriculum.py
import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import SourceDoc, TopicFoundation, TopicIntent


def _client(session):
    app.dependency_overrides[get_session] = lambda: session
    payload = json.dumps({
        "overview": "ov",
        "phases": [{"title": "P1", "est_hours": "Wk1",
                    "items": [{"type": "read", "text": "paper", "concept_refs": ["la"]}],
                    "deliverable": {"kind": "blog", "text": "post",
                                    "acceptance_criteria": ["clear"]}}],
        "sidebars": [{"kind": "reference", "title": "Ref", "body": "b"}],
    })
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([LLMResponse(text=payload)])
    return TestClient(app)


def _seed_topic(session):
    from adaptive_academy.models import Topic
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(TopicIntent(topic_id=topic.id, goal="g"))
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["self-attention", "la"],
                prerequisite_map={"self-attention": ["la"]}))
    session.add(SourceDoc(topic_id=topic.id, title="S", url="u", tier=1,
                status="accepted"))
    session.commit()
    return topic.id


def test_generate_then_get_and_export(session):
    client = _client(session)
    tid = _seed_topic(session)

    r = client.post(f"/api/topics/{tid}/curriculum")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["track"]["overview"] == "ov"
    assert body["phases"][0]["deliverable"]["kind"] == "blog"
    assert any(c["name"] == "la" and c["is_load_bearing"] for c in body["concepts"])
    assert body["events"]

    r2 = client.get(f"/api/topics/{tid}/curriculum")
    assert r2.status_code == 200 and r2.json()["phases"][0]["title"] == "P1"

    r3 = client.get(f"/api/topics/{tid}/curriculum.md")
    assert r3.status_code == 200 and "## Phase 1 — P1" in r3.text

    app.dependency_overrides.clear()


def test_generate_400_without_foundation_or_accepted(session):
    from adaptive_academy.models import Topic
    client = _client(session)
    topic = Topic(title="bare")
    session.add(topic)
    session.commit()
    session.add(TopicIntent(topic_id=topic.id, goal="g"))
    session.commit()
    r = client.post(f"/api/topics/{topic.id}/curriculum")
    assert r.status_code == 400
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_api_curriculum.py -q`
Expected: 404/AttributeError (routes not defined).

- [ ] **Step 3: Implement routes + serializer**

In `src/adaptive_academy/api/routes_topics.py`, extend the imports and add the routes. Add to the schema import block: `CurriculumOut, DeliverableOut, ImportMarkdownIn, ItemOut, PhaseOut, SidebarOut, TrackOut`. Add model imports: `Deliverable, Item, Phase, Sidebar`. Add engine imports:

```python
from fastapi.responses import PlainTextResponse

from adaptive_academy.engine.curriculum import generate_curriculum
from adaptive_academy.engine.track_markdown import (
    DeliverableView, ItemView, PhaseView, SidebarView, TrackView,
    markdown_to_track, track_to_markdown,
)
```

Add a `has_track` lookup to `_topic_out` (after `has_foundation`):

```python
    has_track = (
        session.exec(select(Track).where(Track.topic_id == topic.id)).first() is not None
    )
```
and pass `has_track=has_track` into the returned `TopicOut(...)`.

Add the serializer + routes:

```python
def _curriculum_out(session: Session, track: Track, events=None) -> CurriculumOut:
    phases = session.exec(
        select(Phase).where(Phase.track_id == track.id).order_by(Phase.position)
    ).all()
    phase_outs = []
    for p in phases:
        items = session.exec(
            select(Item).where(Item.phase_id == p.id).order_by(Item.position)
        ).all()
        deliverable = session.exec(
            select(Deliverable).where(Deliverable.phase_id == p.id)
        ).first()
        phase_outs.append(PhaseOut(
            id=p.id, title=p.title, position=p.position, est_hours=p.est_hours,
            flags=p.flags,
            items=[ItemOut(id=i.id, text=i.text, type=i.type, status=i.status,
                           position=i.position) for i in items],
            deliverable=DeliverableOut(id=deliverable.id, kind=deliverable.kind,
                                       text=deliverable.text,
                                       acceptance_criteria=deliverable.acceptance_criteria)
            if deliverable else None,
        ))
    sidebars = session.exec(
        select(Sidebar).where(Sidebar.track_id == track.id).order_by(Sidebar.position)
    ).all()
    concepts = session.exec(select(Concept).where(Concept.track_id == track.id)).all()
    return CurriculumOut(
        track=TrackOut(id=track.id, title=track.title, overview=track.overview),
        phases=phase_outs,
        sidebars=[SidebarOut(id=s.id, kind=s.kind, title=s.title, body=s.body,
                             position=s.position) for s in sidebars],
        concepts=[ConceptOut(id=c.id, name=c.name, is_load_bearing=c.is_load_bearing)
                  for c in concepts],
        events=[EventOut(kind=e.kind, detail=e.detail) for e in (events or [])],
    )


def _track_view(session: Session, track: Track) -> TrackView:
    phases = session.exec(
        select(Phase).where(Phase.track_id == track.id).order_by(Phase.position)
    ).all()
    pvs = []
    for p in phases:
        items = session.exec(
            select(Item).where(Item.phase_id == p.id).order_by(Item.position)
        ).all()
        d = session.exec(select(Deliverable).where(Deliverable.phase_id == p.id)).first()
        pvs.append(PhaseView(
            title=p.title, est_hours=p.est_hours, flags=p.flags,
            items=[ItemView(text=i.text, type=i.type, status=i.status) for i in items],
            deliverable=DeliverableView(text=d.text, kind=d.kind,
                                        acceptance_criteria=d.acceptance_criteria)
            if d else None,
        ))
    sidebars = session.exec(
        select(Sidebar).where(Sidebar.track_id == track.id).order_by(Sidebar.position)
    ).all()
    return TrackView(
        title=track.title, overview=track.overview, phases=pvs,
        sidebars=[SidebarView(kind=s.kind, title=s.title, body=s.body) for s in sidebars])


@router.post("/{topic_id}/curriculum", response_model=CurriculumOut)
def generate_curriculum_route(
    topic_id: int,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
) -> CurriculumOut:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(404, "topic not found")
    intent = session.exec(select(TopicIntent).where(TopicIntent.topic_id == topic_id)).first()
    if intent is None:
        raise HTTPException(400, "topic has no intent")
    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)).first()
    if foundation is None:
        raise HTTPException(400, "topic has no foundation; run research first")
    accepted = session.exec(
        select(SourceDoc).where(SourceDoc.topic_id == topic_id,
                                SourceDoc.status == "accepted")).all()
    if not accepted:
        raise HTTPException(400, "no accepted sources; review the reading list first")
    accepted.sort(key=lambda s: s.rank)
    result = generate_curriculum(session, topic, intent, foundation, accepted, llm=llm)
    return _curriculum_out(session, result.track, result.events)


@router.get("/{topic_id}/curriculum", response_model=CurriculumOut)
def get_curriculum(topic_id: int, session: Session = Depends(get_session)) -> CurriculumOut:
    track = session.exec(select(Track).where(Track.topic_id == topic_id)).first()
    if track is None:
        raise HTTPException(404, "no curriculum yet")
    return _curriculum_out(session, track)


@router.get("/{topic_id}/curriculum.md", response_class=PlainTextResponse)
def export_curriculum(topic_id: int, session: Session = Depends(get_session)) -> str:
    track = session.exec(select(Track).where(Track.topic_id == topic_id)).first()
    if track is None:
        raise HTTPException(404, "no curriculum yet")
    return track_to_markdown(_track_view(session, track))


@router.post("/{topic_id}/curriculum/import", response_model=CurriculumOut)
def import_curriculum(
    topic_id: int, body: ImportMarkdownIn, session: Session = Depends(get_session),
) -> CurriculumOut:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(404, "topic not found")
    view = markdown_to_track(body.markdown)
    # Replace any existing track for this topic.
    old = session.exec(select(Track).where(Track.topic_id == topic_id)).all()
    for t in old:
        for p in session.exec(select(Phase).where(Phase.track_id == t.id)).all():
            for it in session.exec(select(Item).where(Item.phase_id == p.id)).all():
                session.delete(it)
            d = session.exec(select(Deliverable).where(Deliverable.phase_id == p.id)).first()
            if d:
                session.delete(d)
            session.delete(p)
        for s in session.exec(select(Sidebar).where(Sidebar.track_id == t.id)).all():
            session.delete(s)
        session.delete(t)
    session.commit()

    track = Track(topic_id=topic_id, title=view.title, overview=view.overview)
    session.add(track)
    session.commit()
    session.refresh(track)
    for pi, pv in enumerate(view.phases):
        phase = Phase(track_id=track.id, title=pv.title, position=pi,
                      est_hours=pv.est_hours, flags=pv.flags)
        session.add(phase)
        session.commit()
        session.refresh(phase)
        for ii, iv in enumerate(pv.items):
            session.add(Item(phase_id=phase.id, text=iv.text, type=iv.type,
                             status=iv.status, position=ii))
        if pv.deliverable:
            session.add(Deliverable(phase_id=phase.id, kind=pv.deliverable.kind,
                                    text=pv.deliverable.text,
                                    acceptance_criteria=pv.deliverable.acceptance_criteria))
    for si, sv in enumerate(view.sidebars):
        session.add(Sidebar(track_id=track.id, kind=sv.kind, title=sv.title,
                            body=sv.body, position=si))
    session.commit()
    session.refresh(track)
    return _curriculum_out(session, track)
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_api_curriculum.py -q`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/api/routes_topics.py tests/test_api_curriculum.py
git commit -m "feat(api): curriculum generate/get/export/import routes"
```

---

### Task 12: Item PATCH route (editable UI)

**Files:**
- Create: `src/adaptive_academy/api/routes_items.py`
- Modify: `src/adaptive_academy/api/app.py`
- Test: `tests/test_api_items.py` (create)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_api_items.py
from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.models import Item, Phase, Topic, Track


def test_patch_item_status(session):
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    phase = Phase(track_id=track.id, title="p", position=0)
    session.add(phase)
    session.commit()
    item = Item(phase_id=phase.id, text="x", type="read", position=0)
    session.add(item)
    session.commit()

    client = TestClient(app)
    r = client.patch(f"/api/items/{item.id}", json={"status": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert client.patch("/api/items/9999", json={"status": "done"}).status_code == 404
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run it to confirm it fails**

Run: `uv run pytest tests/test_api_items.py -q`
Expected: 404 (route not registered).

- [ ] **Step 3: Implement the router + register it**

```python
# src/adaptive_academy/api/routes_items.py
from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_session
from adaptive_academy.api.schemas import ItemOut, ItemPatchIn
from adaptive_academy.models import Item

router = APIRouter(prefix="/api/items", tags=["items"])

_VALID_STATUS = {"todo", "doing", "done"}


@router.patch("/{item_id}", response_model=ItemOut)
def patch_item(item_id: int, body: ItemPatchIn, session: Session = Depends(get_session)) -> ItemOut:
    item = session.get(Item, item_id)
    if item is None:
        raise HTTPException(404, "item not found")
    if body.status is not None:
        if body.status not in _VALID_STATUS:
            raise HTTPException(422, "invalid status")
        item.status = body.status
    if body.text is not None:
        item.text = body.text
    session.add(item)
    session.commit()
    session.refresh(item)
    return ItemOut(id=item.id, text=item.text, type=item.type, status=item.status,
                   position=item.position)
```

In `src/adaptive_academy/api/app.py`, import and include the router (match the existing `include_router` calls):

```python
from adaptive_academy.api.routes_items import router as items_router
...
app.include_router(items_router)
```

- [ ] **Step 4: Run the test to confirm it passes**

Run: `uv run pytest tests/test_api_items.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/adaptive_academy/api/routes_items.py src/adaptive_academy/api/app.py tests/test_api_items.py
git commit -m "feat(api): PATCH /api/items/{id} for editable tracker"
```

---

### Task 13: Integration test — research → curriculum → Tutor-on-generated-Concept

**Files:**
- Test: `tests/test_integration_loop.py` (create)

- [ ] **Step 1: Write the test**

```python
# tests/test_integration_loop.py
import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse


def test_research_to_curriculum_to_tutor(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "foundational_papers": [RawSource(title="Attention",
            url="https://arxiv.org/abs/1706.03762", tier=1, relevance=0.95, summary="s")],
    })
    # 1 LLM call for foundation synthesis, 1 for curriculum, then tutor replies.
    foundation_json = json.dumps({"overview": "o", "key_concepts": ["self-attention", "la"],
                                  "prerequisite_map": {"self-attention": ["la"]}})
    curriculum_json = json.dumps({"overview": "ov", "phases": [
        {"title": "P1", "items": [{"type": "build", "text": "nanoGPT",
                                   "concept_refs": ["self-attention"]}],
         "deliverable": {"kind": "repo", "text": "repo", "acceptance_criteria": ["trains"]}}],
        "sidebars": []})
    # ONE shared client; responses are consumed in sequence across requests:
    # research foundation synth -> curriculum generation -> tutor turn.
    shared_llm = ScriptedLLMClient([
        LLMResponse(text=foundation_json),
        LLMResponse(text=curriculum_json),
        LLMResponse(text="What have you tried so far?"),  # tutor turn (no tool calls)
    ])
    app.dependency_overrides[get_llm] = lambda: shared_llm
    client = TestClient(app)

    tid = client.post("/api/topics", json={"title": "Build LLMs", "goal": "build a GPT"}).json()["id"]
    client.post(f"/api/topics/{tid}/research")
    sources = client.get(f"/api/topics/{tid}/sources").json()
    client.post(f"/api/topics/{tid}/sources/review",
                json={"accepted_ids": [s["id"] for s in sources], "pruned_ids": []})

    cur = client.post(f"/api/topics/{tid}/curriculum").json()
    concept_id = cur["concepts"][0]["id"]

    convo = client.post("/api/conversations", json={"topic_id": tid, "concept_id": concept_id}).json()
    assert convo["assistance_level"] == "low"  # generated estimate level=high -> low assistance
    reply = client.post(f"/api/conversations/{convo['id']}/messages",
                        json={"content": "explain attention"}).json()
    assert reply["reply"]
    app.dependency_overrides.clear()
```

- [ ] **Step 2: Run it**

Run: `uv run pytest tests/test_integration_loop.py -q`
Expected: PASS. (If the Tutor makes >1 LLM call before replying, add more `LLMResponse` entries with plain text so the scripted client doesn't run dry.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_integration_loop.py
git commit -m "test: integration loop research->curriculum->tutor on generated concept"
```

---

### Task 14: Frontend types + api clients

**Files:**
- Modify: `frontend/src/lib/types.ts`, `frontend/src/lib/api.ts`, `frontend/src/lib/api.test.ts`

- [ ] **Step 1: Add types**

Append to `frontend/src/lib/types.ts`:

```typescript
export interface Item { id: number; text: string; type: string; status: string; position: number; }
export interface Deliverable { id: number; kind: string; text: string; acceptance_criteria: string[]; }
export interface Sidebar { id: number; kind: string; title: string; body: string; position: number; }
export interface Phase {
  id: number; title: string; position: number; est_hours: string; flags: string[];
  items: Item[]; deliverable: Deliverable | null;
}
export interface TrackInfo { id: number; title: string; overview: string; }
export interface Curriculum {
  track: TrackInfo; phases: Phase[]; sidebars: Sidebar[]; concepts: Concept[]; events: EventOut[];
}
```

- [ ] **Step 2: Add api clients**

Add to the `api` object in `frontend/src/lib/api.ts` (and extend the type import line with `Curriculum, Item`):

```typescript
  generateCurriculum: (topicId: number) =>
    fetch(`/api/topics/${topicId}/curriculum`, { method: 'POST' }).then(j<Curriculum>),
  getCurriculum: (topicId: number) =>
    fetch(`/api/topics/${topicId}/curriculum`).then(j<Curriculum>),
  exportCurriculumMd: (topicId: number) =>
    fetch(`/api/topics/${topicId}/curriculum.md`).then((r) => r.text()),
  updateItem: (itemId: number, patch: { status?: string; text?: string }) =>
    fetch(`/api/items/${itemId}`, {
      method: 'PATCH',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(patch)
    }).then(j<Item>),
```

- [ ] **Step 3: Add a client test**

Append a test to `frontend/src/lib/api.test.ts` (follow the existing `vi.fn()` fetch-mock pattern already in that file) covering `generateCurriculum` (POST to `/api/topics/1/curriculum`) and `updateItem` (PATCH to `/api/items/5` with `{status:'done'}`).

- [ ] **Step 4: Run frontend tests**

Run: `cd frontend && npm test`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/api.ts frontend/src/lib/api.test.ts
git commit -m "feat(frontend): curriculum types + api clients"
```

---

### Task 15: Frontend track page + review "Generate curriculum" action

**Files:**
- Create: `frontend/src/routes/topics/[id]/track/+page.svelte`
- Modify: `frontend/src/routes/topics/[id]/review/+page.svelte`

- [ ] **Step 1: Create the track page**

```svelte
<!-- frontend/src/routes/topics/[id]/track/+page.svelte -->
<script lang="ts">
  import { page } from '$app/stores';
  import { onMount } from 'svelte';
  import { api } from '$lib/api';
  import type { Curriculum } from '$lib/types';

  const topicId = Number($page.params.id);
  let cur = $state<Curriculum | null>(null);
  const cycle: Record<string, string> = { todo: 'doing', doing: 'done', done: 'todo' };

  onMount(async () => {
    try { cur = await api.getCurriculum(topicId); } catch { cur = null; }
  });

  async function toggle(itemId: number, status: string) {
    const next = cycle[status] ?? 'todo';
    const updated = await api.updateItem(itemId, { status: next });
    if (!cur) return;
    for (const p of cur.phases)
      for (const it of p.items) if (it.id === itemId) it.status = updated.status;
  }

  async function exportMd() {
    const md = await api.exportCurriculumMd(topicId);
    const blob = new Blob([md], { type: 'text/markdown' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url; a.download = `track-${topicId}.md`; a.click();
    URL.revokeObjectURL(url);
  }
</script>

<main class="mx-auto max-w-3xl p-6 flex flex-col gap-4">
  {#if cur}
    <div class="flex items-center justify-between">
      <h1 class="text-xl font-semibold">{cur.track.title}</h1>
      <button class="text-sm underline" onclick={exportMd}>Export markdown</button>
    </div>
    {#if cur.track.overview}<p class="text-sm text-gray-600">{cur.track.overview}</p>{/if}

    {#each cur.phases as p (p.id)}
      <section class="border rounded p-4 flex flex-col gap-2">
        <h2 class="font-medium">
          Phase {p.position + 1} — {p.title}
          {#if p.est_hours}<span class="text-xs text-gray-500">({p.est_hours})</span>{/if}
          {#each p.flags as f}<span class="text-xs bg-gray-200 rounded px-1">{f}</span>{/each}
        </h2>
        <ul class="flex flex-col gap-1">
          {#each p.items as it (it.id)}
            <li class="flex gap-2 items-center text-sm">
              <button class="font-mono text-xs border rounded px-1"
                      onclick={() => toggle(it.id, it.status)}>{it.status}</button>
              <span class="text-xs text-gray-500">({it.type})</span>
              <span>{it.text}</span>
            </li>
          {/each}
        </ul>
        {#if p.deliverable}
          <div class="text-sm bg-yellow-50 border rounded p-2">
            🎯 Ship ({p.deliverable.kind}): {p.deliverable.text}
            {#if p.deliverable.acceptance_criteria.length}
              <ul class="list-disc ml-5 text-xs text-gray-600">
                {#each p.deliverable.acceptance_criteria as c}<li>{c}</li>{/each}
              </ul>
            {/if}
          </div>
        {/if}
      </section>
    {/each}

    {#each cur.sidebars as s (s.id)}
      <aside class="border-l-4 border-gray-300 pl-3 text-sm">
        <div class="font-medium">{s.title} <span class="text-xs text-gray-500">{s.kind}</span></div>
        <p class="text-gray-600 whitespace-pre-line">{s.body}</p>
      </aside>
    {/each}

    {#if cur.events.length}
      <details class="text-sm text-gray-600">
        <summary class="cursor-pointer">What the agents did ({cur.events.length})</summary>
        <ul class="mt-2 flex flex-col gap-1">
          {#each cur.events as e}<li><span class="font-mono text-xs">{e.kind}</span> — {e.detail}</li>{/each}
        </ul>
      </details>
    {/if}
  {:else}
    <p class="text-sm text-gray-500">No curriculum yet.</p>
  {/if}
</main>
```

- [ ] **Step 2: Add the "Generate curriculum" action to the review page**

In `frontend/src/routes/topics/[id]/review/+page.svelte`, import `goto` from `$app/navigation`, and after a successful `save()` (when `saved` is true) render a button that generates the curriculum and navigates:

```svelte
  import { goto } from '$app/navigation';
  ...
  let generating = $state(false);
  async function generate() {
    generating = true;
    try {
      await api.generateCurriculum(topicId);
      await goto(`/topics/${topicId}/track`);
    } finally {
      generating = false;
    }
  }
```

Add, near the save button (shown once `saved`):

```svelte
  {#if saved}
    <button class="bg-black text-white rounded px-4 py-2 disabled:opacity-50 self-start"
            onclick={generate} disabled={generating}>
      {generating ? 'Generating…' : 'Generate curriculum →'}
    </button>
  {/if}
```

- [ ] **Step 3: Type-check + build**

Run: `cd frontend && npm run check && npm run build`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/routes/topics/
git commit -m "feat(frontend): editable track page + generate-curriculum action"
```

---

### Task 16: Full-suite verification

**Files:** none (verification only)

- [ ] **Step 1: Backend tests + lint**

Run: `uv run pytest -q && uv run ruff check src tests`
Expected: all green (existing 38 + new curriculum/api/integration tests).

- [ ] **Step 2: Migration round-trip + seed**

Run:
```bash
uv run alembic upgrade head && uv run alembic downgrade -1 && uv run alembic upgrade head
uv run python -c "from adaptive_academy.seed import seed; seed()"
```
Expected: no errors.

- [ ] **Step 3: Frontend tests + build**

Run: `cd frontend && npm test && npm run build`
Expected: all green.

- [ ] **Step 4: Commit (if any lint fixups were needed)**

```bash
git add -A && git commit -m "chore: lint + verification fixups" || echo "nothing to commit"
```

---

## Self-Review

**Spec coverage:**
- `POST /curriculum` → Track with ordered Phases/typed Items/per-phase Deliverable/Sidebars → Tasks 9, 11. ✅
- Concepts materialized with `is_load_bearing` + seeded estimates → Tasks 5, 9 (asserted in test). ✅
- Evidence rules + **code-enforced spacing** → Tasks 6, 8, 9. ✅
- Markdown round-trip (`Track → md → Track` equality) → Tasks 3, 4. ✅
- Editable tracker UI (status cycle + export) → Tasks 12, 14, 15. ✅
- New data model + migration; Plan 1/2 paths intact → Tasks 1, 2, 16. ✅
- Generation unit-tested with scripted client; round-trip + spacing pure & tested; integration test research→curriculum→tutor → Tasks 4, 6, 9, 13. ✅

**Type consistency:** `TrackView/PhaseView/ItemView/DeliverableView/SidebarView` are defined once in `track_markdown.py` and reused by `curriculum.py` (draft) and the markdown pair — no divergent shapes. `ItemView.concept_refs` is carried in the draft/DB but intentionally not serialized (round-trip fixtures use `[]`). Out schemas (`CurriculumOut` etc.) match `_curriculum_out`.

**Placeholder scan:** none — every step has complete code.
