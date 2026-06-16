from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import Column, JSON
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
    """Observability trace: one row per engine/agent step.

    Exactly one of conversation_id / topic_id is set (app-level invariant).
    """

    id: Optional[int] = Field(default=None, primary_key=True)
    conversation_id: Optional[int] = Field(default=None, foreign_key="conversation.id")
    topic_id: Optional[int] = Field(default=None, foreign_key="topic.id")
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


class TopicFoundation(SQLModel, table=True):
    """Synthesized overview + concept map for a Topic (decoupled from Track/Concept)."""

    id: Optional[int] = Field(default=None, primary_key=True)
    topic_id: int = Field(foreign_key="topic.id", unique=True)
    overview: str = ""
    key_concepts: list[str] = Field(default_factory=list, sa_column=Column(JSON))
    prerequisite_map: dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSON))
    created_at: datetime = Field(default_factory=_now)
