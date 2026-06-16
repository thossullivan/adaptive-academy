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
    has_track: bool = False


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
