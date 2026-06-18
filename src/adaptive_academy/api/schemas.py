from typing import Optional

from pydantic import BaseModel


class ConceptOut(BaseModel):
    id: int
    name: str
    is_load_bearing: bool
    last_assessment_score: Optional[float] = None
    has_anchor: bool = False


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
    is_remediation: bool = False


class DeliverableOut(BaseModel):
    id: int
    kind: str
    text: str
    acceptance_criteria: list[str]
    artifact_url: str = ""
    review_verdict: str = ""


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


class AssessIn(BaseModel):
    kind: str
    response: str = ""
    confidence_predicted: Optional[float] = None
    baseline_id: Optional[int] = None
    item_id: Optional[int] = None
    anchor_id: Optional[int] = None


class AssessmentOut(BaseModel):
    id: int
    kind: str
    prompt: str
    response: str
    verdict: str
    score: float
    gaps: list[str]
    confidence_predicted: Optional[float] = None
    confidence_actual: Optional[float] = None
    delta: Optional[float] = None
    estimate_level: Optional[str] = None


class RubricOut(BaseModel):
    id: int
    concept_id: int
    criteria: list[str]
    must_include: list[str]
    strong_signs: list[str]
    weak_signs: list[str]
    reviewed_by_user: bool


class SRSCardOut(BaseModel):
    id: int
    concept_id: int
    front: str
    back: str
    status: str
    interval: int
    reps: int
    last_result: str


class RecallPromptOut(BaseModel):
    id: int
    concept_id: int
    prompt: str
    status: str


class RetentionOut(BaseModel):
    cards: list[SRSCardOut]
    prompts: list[RecallPromptOut]


class ProposeRetentionIn(BaseModel):
    from_assessment_id: Optional[int] = None


class CardReviewIn(BaseModel):
    status: str  # active | suspended


class CardGradeIn(BaseModel):
    result: str  # again | hard | good | easy


class RemediateIn(BaseModel):
    from_assessment_id: Optional[int] = None


class RemediationOut(BaseModel):
    items: list[ItemOut]
    events: list[EventOut]


class AnchorOut(BaseModel):
    id: int
    source_doc_id: int
    concept_id: Optional[int] = None
    question: str
    reference_answer: str
    key_points: list[str]


class AnchorGenOut(BaseModel):
    anchors: list[AnchorOut]
    events: list[EventOut]


class StoryOut(BaseModel):
    headline: str
    narrative: list[str]
    highlights: list[str]
    facts: dict
    events: list[EventOut]


class DecayItemOut(BaseModel):
    prompt_id: int
    concept_id: int
    concept_name: str
    prompt: str
    last_result: str


class DecayDueOut(BaseModel):
    items: list[DecayItemOut]


class DecayGradeIn(BaseModel):
    response: str


class DecayGradeOut(BaseModel):
    recall_score: float
    baseline_score: Optional[float] = None
    decay_delta: Optional[float] = None
    held: bool
    verdict: str
    gaps: list[str]
    estimate_level: str


class ChallengeOut(BaseModel):
    problem: str


class ConsolidateIn(BaseModel):
    problem: str
    attempt: str


class ConsolidateOut(BaseModel):
    canonical: str
    feedback: str
    score: float


class TeachIn(BaseModel):
    explanation: str


class TeachOut(BaseModel):
    score: float
    feedback: str
    strengths: list[str]
    gaps: list[str]


class ShipIn(BaseModel):
    artifact_url: str = ""
    content: str


class ArtifactReviewOut(BaseModel):
    score: float
    verdict: str
    gaps: list[str]
    concepts: list[str]


class VaultIngestIn(BaseModel):
    vault_path: str = ""  # overrides settings.obsidian_vault_path when set
    subfolder: str = ""


class VaultIngestOut(BaseModel):
    count: int
    titles: list[str] = []


class VaultExportIn(BaseModel):
    vault_path: str = ""


class VaultExportOut(BaseModel):
    written: list[str] = []


class VaultStatusOut(BaseModel):
    configured: bool
    path: str = ""
    exists: bool = False
    is_dir: bool = False
    note_count: int = 0


class VaultExportAllOut(BaseModel):
    topics: int
    written: list[str] = []


class WindStateOut(BaseModel):
    topic_id: int
    topic_title: str
    value: float
    state: str
    last_sailed: Optional[str] = None
    days_since: Optional[float] = None
    progress: float = 0.0  # distance: fraction of curriculum done (orthogonal to wind)


class ComebackMoveOut(BaseModel):
    kind: str
    label: str
    href: str
    minutes: int


class ComebackOut(BaseModel):
    move: Optional[ComebackMoveOut] = None
