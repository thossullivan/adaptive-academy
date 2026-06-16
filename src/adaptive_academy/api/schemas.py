from typing import Optional

from pydantic import BaseModel


class ConceptOut(BaseModel):
    id: int
    name: str
    is_load_bearing: bool


class IntentOut(BaseModel):
    goal: str
    prior_knowledge: str
    time_budget: str


class TopicOut(BaseModel):
    id: int
    title: str
    concepts: list[ConceptOut]
    intent: Optional[IntentOut] = None
    has_foundation: bool = False


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


class CreateTopicIn(BaseModel):
    title: str
    goal: str
    prior_knowledge: str = ""
    time_budget: str = ""


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
