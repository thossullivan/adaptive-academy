from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, Index, JSON, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel


def _now() -> datetime:
    return datetime.now(timezone.utc)


now_utc = _now  # public alias for callers outside this module (e.g. API routes)


class Topic(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    title: str
    created_at: datetime = Field(default_factory=_now)
    tracks: list["Track"] = Relationship(back_populates="topic")


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


class RoleplaySession(SQLModel, table=True):
    """A persona-driven adversarial roleplay tied to a Program milestone."""

    id: Optional[int] = Field(default=None, primary_key=True)
    program_id: int = Field(foreign_key="program.id")
    milestone_id: int = Field(foreign_key="milestone.id")
    status: str = "briefing"  # briefing | active | ended | graded
    persona_brief: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    outcome: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class RoleplayTurn(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    session_id: int = Field(foreign_key="roleplaysession.id")
    role: str  # "user" | "persona"
    content: str
    created_at: datetime = Field(default_factory=_now)


class PaperProbe(SQLModel, table=True):
    """A critical paper-reading probe tied to a Program milestone."""

    id: Optional[int] = Field(default=None, primary_key=True)
    program_id: int = Field(foreign_key="program.id")
    milestone_id: int = Field(foreign_key="milestone.id")
    paper_title: str = ""
    paper_url: str = ""
    paper_text: str = ""
    source: str = "paste"  # arxiv | paste
    status: str = "drafting"  # drafting | answering | graded
    questions: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    outcome: Optional[dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
    updated_at: datetime = Field(default_factory=_now)


class PaperProbeAnswer(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    probe_id: int = Field(foreign_key="paperprobe.id")
    question_index: int
    content: str
    created_at: datetime = Field(default_factory=_now)


class AgentEvent(SQLModel, table=True):
    """Observability trace: one row per engine/agent step.

    Exactly one of conversation_id / topic_id / program_id is set (app-level invariant).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id")
    topic_id: Optional[int] = Field(default=None, foreign_key="topic.id")
    program_id: Optional[int] = Field(default=None, foreign_key="program.id")
    roleplay_session_id: Optional[int] = Field(default=None, foreign_key="roleplaysession.id")
    paper_probe_id: Optional[int] = Field(default=None, foreign_key="paperprobe.id")
    kind: str
    detail: str = ""
    created_at: datetime = Field(default_factory=_now)


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


class Chunk(SQLModel, table=True):
    """One indexed span of text used for retrieval and deduplication."""

    __table_args__ = (
        UniqueConstraint("source_ref", "ordinal", name="uq_chunk_source_ref_ordinal"),
        Index("ix_chunk_kind_topic_id", "kind", "topic_id"),
        Index("ix_chunk_kind_concept_id", "kind", "concept_id"),
        Index("ix_chunk_source_ref", "source_ref"),
        Index("ix_chunk_created_at", "created_at"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    kind: str
    topic_id: Optional[int] = Field(default=None, foreign_key="topic.id")
    concept_id: Optional[int] = Field(default=None, foreign_key="concept.id")
    source_ref: str
    ordinal: int = 0
    heading: str = ""
    text: str
    context: str = ""
    content_hash: str
    meta: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    source_mtime: Optional[float] = None
    embedding_model: Optional[str] = None
    created_at: datetime = Field(default_factory=_now)


class VaultLink(SQLModel, table=True):
    """One resolved or unresolved wikilink from a vault note."""

    __table_args__ = (
        Index("ix_vaultlink_src_ref", "src_ref"),
        Index("ix_vaultlink_dst_ref", "dst_ref"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    src_ref: str
    dst_ref: str
    dst_title: str


class TopicFoundation(SQLModel, table=True):
    """Synthesized overview + concept map for a Topic (decoupled from Track/Concept)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", unique=True)
    overview: str = ""
    key_concepts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    prerequisite_map: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


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
    added_by: str = "curriculum"  # "curriculum" | "remediation"
    remediation_key: str = ""  # idempotency signature for remediation items
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


class Rubric(SQLModel, table=True):
    """Anchor the Assessor grades a concept's explanation against (§2.4)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concept.id", unique=True)
    criteria: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    must_include: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    strong_signs: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    weak_signs: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    source_refs: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    reviewed_by_user: bool = False
    created_at: datetime = Field(default_factory=_now)


class ReferenceAnchor(SQLModel, table=True):
    """Ground truth for a source-derived quiz question (§2.4)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    source_doc_id: int = Field(foreign_key="sourcedoc.id")
    concept_id: Optional[int] = Field(default=None, foreign_key="concept.id")
    question: str
    reference_answer: str = ""
    key_points: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)


class Assessment(SQLModel, table=True):
    """A graded probe outcome, always recorded against an anchor (§2.4)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concept.id")
    item_id: Optional[int] = Field(default=None, foreign_key="item.id")
    kind: str  # self_explanation | calibration | artifact_review | source_quiz | recall
    prompt: str
    response: str = ""
    verdict: str = ""
    score: float = 0.0  # 0..1, anchored
    gaps: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    confidence_predicted: Optional[float] = None
    confidence_actual: Optional[float] = None
    rubric_id: Optional[int] = Field(default=None, foreign_key="rubric.id")
    anchor_id: Optional[int] = Field(default=None, foreign_key="referenceanchor.id")
    roleplay_session_id: Optional[int] = Field(default=None, foreign_key="roleplaysession.id")
    paper_probe_id: Optional[int] = Field(default=None, foreign_key="paperprobe.id")
    baseline_assessment_id: Optional[int] = Field(default=None, foreign_key="assessment.id")
    delta: Optional[float] = None
    created_at: datetime = Field(default_factory=_now)


class SRSCard(SQLModel, table=True):
    """Curated spaced-repetition card (SM-2), user-reviewed before rotation (§2.2)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concept.id")
    front: str
    back: str
    source_ref: str = ""
    status: str = "proposed"  # proposed | active | suspended
    ease: float = 2.5
    interval: int = 0
    reps: int = 0
    due_at: datetime = Field(default_factory=_now)
    last_result: str = ""
    created_at: datetime = Field(default_factory=_now)


class RecallPrompt(SQLModel, table=True):
    """Generative free-recall / Feynman prompt (§2.2)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    concept_id: int = Field(foreign_key="concept.id")
    prompt: str
    status: str = "proposed"  # proposed | active | suspended
    due_at: datetime = Field(default_factory=_now)
    last_result: str = ""
    created_at: datetime = Field(default_factory=_now)


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
    archived: bool = False
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
    added_by: str = "research"  # "research" | "revision" | "scout"
    created_at: datetime = Field(default_factory=_now)


class ConceptAlias(SQLModel, table=True):
    """Cross-topic concept identity inside a Program (knowledge carryover, spec §4.4)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    program_id: int = Field(foreign_key="program.id")
    canonical_name: str
    concept_id: int = Field(foreign_key="concept.id", unique=True)
    created_at: datetime = Field(default_factory=_now)


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


class ConceptEdge(SQLModel, table=True):
    """Directed, typed, bi-temporal edge between two concepts."""

    __table_args__ = (
        Index(
            "ix_conceptedge_src_concept_id_valid_until",
            "src_concept_id",
            "valid_until",
        ),
        Index(
            "ix_conceptedge_dst_concept_id_valid_until",
            "dst_concept_id",
            "valid_until",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    src_concept_id: int = Field(foreign_key="concept.id")
    dst_concept_id: int = Field(foreign_key="concept.id")
    kind: str  # prerequisite | related | alias
    weight: float = 1.0
    origin: str  # researcher | revision | alias | learner
    origin_ref: str = ""
    valid_from: datetime = Field(default_factory=_now)
    valid_until: Optional[datetime] = None
    recorded_at: datetime = Field(default_factory=_now)


class ChunkConcept(SQLModel, table=True):
    """Which concepts a chunk mentions after deterministic string matching."""

    __table_args__ = (
        UniqueConstraint(
            "chunk_id",
            "concept_id",
            name="uq_chunkconcept_chunk_id_concept_id",
        ),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    chunk_id: int = Field(foreign_key="chunk.id")
    concept_id: int = Field(foreign_key="concept.id")
    hits: int = 1


class TopicSuggestion(SQLModel, table=True):
    __table_args__ = (
        Index("ix_topicsuggestion_status_program_id", "status", "program_id"),
    )

    id: Optional[int] = Field(default=None, primary_key=True)
    program_id: Optional[int] = Field(default=None, foreign_key="program.id")
    title: str
    rationale: str
    candidate_kind: str  # frontier | orphan_term | orphan_note | extension
    evidence: list[dict[str, Any]] = Field(default_factory=list, sa_column=Column(JSON))
    score: float = 0.0
    status: str = "proposed"  # proposed | accepted | dismissed
    created_at: datetime = Field(default_factory=_now)
    decided_at: Optional[datetime] = None
