from pydantic import BaseModel


class ConceptOut(BaseModel):
    id: int
    name: str
    is_load_bearing: bool


class TopicOut(BaseModel):
    id: int
    title: str
    concepts: list[ConceptOut]


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
