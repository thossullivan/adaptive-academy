from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, field_validator


class ConceptOut(BaseModel):
    id: int
    name: str
    is_load_bearing: bool
    last_assessment_score: Optional[float] = None
    has_anchor: bool = False


class EdgeOut(BaseModel):
    src: int
    dst: int
    kind: str
    weight: float


class GraphOut(BaseModel):
    nodes: list[ConceptOut]
    edges: list[EdgeOut]


class TopicSuggestionOut(BaseModel):
    id: int
    program_id: int
    title: str
    rationale: str
    candidate_kind: str
    evidence: list[dict]
    score: float
    status: str
    created_at: datetime
    decided_at: Optional[datetime]


class ScoutOut(BaseModel):
    suggestions: list[TopicSuggestionOut]
    candidates: dict[str, int]
    truncated: bool


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
    is_demo: bool = False
    # Research for this topic is running now (engine/runlock.py), as opposed to a run that
    # stopped without finishing.
    research_running: bool = False
    # POST /research would start a run: no foundation yet, or one that came with no sources
    # (engine/research.py research_can_rerun).
    can_research: bool = True


class StartConversationIn(BaseModel):
    topic_id: int
    concept_id: int


class MessageOut(BaseModel):
    role: str
    content: str
    is_attempt: bool = False  # the learner sent it with Submit attempt
    # The check's verdict on a submitted attempt (its Attempt row): true accepted, false not
    # logged, None when there is no verdict (not an attempt, the check was unavailable, or an
    # attempt in a conversation that was already unlocked).
    attempt_accepted: Optional[bool] = None
    # A tutor reply that is a worked solution, shown because an attempt was logged.
    reveals_solution: bool = False


class MemoryHitOut(BaseModel):
    chunk_id: int
    kind: str
    heading: str
    snippet: str
    score: float
    source_ref: str


class MemorySearchOut(BaseModel):
    hits: list[MemoryHitOut] = []


class MemoryReindexIn(BaseModel):
    topic_id: Optional[int] = None
    vault_path: str = ""
    kinds: Optional[list[str]] = None


class MemoryReindexOut(BaseModel):
    indexed: int
    skipped: int
    removed: int
    truncated: bool
    ms: int
    note: str = ""


class MemoryStatsOut(BaseModel):
    by_kind: dict[str, int]
    last_indexed_at: Optional[datetime] = None
    retriever: str


class EventOut(BaseModel):
    kind: str
    detail: str
    created_at: Optional[datetime] = None  # set by the trace-list endpoints


class SendMessageIn(BaseModel):
    content: str
    # The Submit attempt button: check the message and record it as the learner's attempt
    # before the tutor runs (engine/attempt.py). Send leaves it false.
    attempt: bool = False

    @field_validator("content")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        # Rejected here, before any model call: a blank attempt would otherwise pay for an
        # attempt check and store a rejected row, and a blank message reaches the tutor.
        if not value.strip():
            raise ValueError("message is empty")
        return value


class ConversationOut(BaseModel):
    id: int
    concept_id: int
    attempt_logged: bool
    assistance_level: str
    challenge_level: str
    messages: list[MessageOut]


class ConversationPreviewOut(BaseModel):
    """The header a new tutor session would open with, read without creating one."""

    concept_id: int
    attempt_logged: bool
    assistance_level: str
    challenge_level: str


AttemptOutcomeOut = Literal["accepted", "rejected", "unverified", "already_logged"]


class SendMessageOut(BaseModel):
    reply: str
    attempt_logged: bool
    # What happened to a submitted attempt (engine/attempt.py); None for an ordinary message.
    attempt_outcome: Optional[AttemptOutcomeOut] = None
    # The reply is a worked solution the attempt unlocked (Message.reveals_solution).
    reveals_solution: bool = False
    assistance_level: str
    challenge_level: str
    events: list[EventOut]
    memory: list[MemoryHitOut] = []


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
    prompt_tag: Optional[str] = None  # grading prompt version; None = unknown (older row)


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
    # Concept notes left unchanged, with why (e.g. notebook markers that don't pair up).
    problems: list[str] = []


class VaultSyncIn(BaseModel):
    vault_path: str = ""  # "" stops syncing to a browser-set vault


class VaultSyncOut(BaseModel):
    """Concept-notebook sync to the vault (engine/notebook_sync.py)."""

    path: str = ""  # where notebooks sync; "" = nowhere
    # Where that path comes from: "browser" (PUT /api/vault/sync), "env"
    # (AA_OBSIDIAN_VAULT_PATH, which only .env can turn off), or "".
    source: Literal["browser", "env", ""] = ""
    last_synced_at: Optional[datetime] = None
    # The most recent problem still unresolved (a note that couldn't be updated), else "".
    last_error: str = ""
    last_error_at: Optional[datetime] = None
    problems: int = 0
    # Notes skipped (problems tied to one concept note); `problems` also counts problems with
    # the sync as a whole (an unusable vault path, a full queue).
    skipped_notes: int = 0
    pending: int = 0


class VaultStatusOut(BaseModel):
    configured: bool
    path: str = ""
    exists: bool = False
    is_dir: bool = False
    note_count: int = 0
    sync: VaultSyncOut = VaultSyncOut()


class VaultExportAllOut(BaseModel):
    topics: int
    written: list[str] = []
    problems: list[str] = []


class NoteIn(BaseModel):
    body: str
    # The browser's vault path, if it has one: registered as the sync target (like
    # PUT /api/vault/sync) so the note reaches the vault. A bad path never fails the save.
    vault_path: str = ""
    # The saved note the editor was showing: its updated_at, or null for "no note yet". When
    # sent and the saved note has changed since (another tab saved), the save is refused
    # with 409 and the note saved now. Left out: no check (older clients).
    base_updated_at: Optional[datetime] = None


class NoteOut(BaseModel):
    concept_id: int
    body: str
    updated_at: datetime
    # The concept's vault note file when its notebook section was edited in Obsidian, so the
    # sync leaves it alone (engine/notebook_sync.locked_note); None when it updates normally.
    vault_locked_note: Optional[str] = None


class NotebookNoteOut(BaseModel):
    body: str
    updated_at: datetime


class NotebookItemOut(BaseModel):
    kind: Literal["attempt", "explanation", "solution"]
    id: int
    created_at: datetime
    source: Literal["tutor", "assess", "teach", "retention"]
    text: str
    conversation_id: Optional[int] = None
    accepted: Optional[bool] = None
    assessment_kind: Optional[str] = None
    label: str = ""
    prompt: str = ""
    score: Optional[float] = None
    verdict: str = ""
    gaps: list[str] = []


class NotebookCountsOut(BaseModel):
    attempts: int
    explanations: int
    solutions: int


class NotebookOut(BaseModel):
    concept_id: int
    concept_name: str
    topic_id: Optional[int]
    note: Optional[NotebookNoteOut] = None
    counts: NotebookCountsOut
    items: list[NotebookItemOut]  # newest first
    vault_locked_note: Optional[str] = None  # as on NoteOut


class NotebookConceptOut(BaseModel):
    concept_id: int
    name: str
    has_note: bool
    attempts: int
    explanations: int
    solutions: int
    last_activity_at: datetime


class TopicNotebookOut(BaseModel):
    topic_id: int
    concepts: list[NotebookConceptOut]  # latest activity first


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
    added_by: str = "research"


class MilestoneOut(BaseModel):
    id: int
    title: str
    success_criteria: str
    order_index: int
    gate_status: str
    depends_on: list[int] = []
    override_reason: str = ""
    links: list[LinkOut] = []
    archived: bool = False


class ProgramDetailOut(BaseModel):
    program: ProgramOut
    milestones: list[MilestoneOut]
    revision_suggested: bool = False
    has_open_revision: bool = False


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
    revision_suggested: bool = False


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


class RoleplayTurnIn(BaseModel):
    content: str


class RoleplayTurnRow(BaseModel):
    role: str
    content: str


class ScorecardRow(BaseModel):
    concept_id: int
    concept: str
    score: float
    verdict: str
    gaps: list[str]
    prompt_tag: Optional[str] = None


class RoleplaySessionOut(BaseModel):
    session_id: int
    program_id: int
    status: str
    brief_public: dict          # persona + situation only
    turns: list[RoleplayTurnRow]
    outcome: Optional[dict] = None
    scorecard: Optional[list[ScorecardRow]] = None


class RoleplayTurnOut(BaseModel):
    reply: str
    status: str
    # False when the persona gave no usable reply (e.g. a model refusal): nothing was stored
    # for the turn and `reply` is a notice for the learner rather than the persona's line.
    recorded: bool = True


class PaperProbeStartIn(BaseModel):
    url: str = ""
    pasted_text: str = ""
    title: str = ""


class PaperProbeAnswerIn(BaseModel):
    question_index: int
    content: str


class PaperQuestionRow(BaseModel):
    index: int
    axis: str
    prompt: str


class PaperProbeAnswerRow(BaseModel):
    question_index: int
    content: str


class PaperProbeOut(BaseModel):
    probe_id: int
    program_id: int
    milestone_id: int
    status: str
    paper: dict  # {title, url, source}
    questions: list[PaperQuestionRow]
    answers: list[PaperProbeAnswerRow] = []
    outcome: Optional[dict] = None
    scorecard: Optional[list[ScorecardRow]] = None


class PaperProbeAnswerOut(BaseModel):
    status: str
