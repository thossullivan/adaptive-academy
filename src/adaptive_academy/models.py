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
