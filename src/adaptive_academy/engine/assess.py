import json
from dataclasses import dataclass, field

from sqlmodel import Session, col, select

from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    Deliverable,
    Item,
    KnowledgeEstimate,
    ReferenceAnchor,
    Rubric,
    SourceDoc,
    TopicFoundation,
)
from adaptive_academy.prompts import GRADE, PROBE_TEXT, RUBRIC
from adaptive_academy.engine.untrusted import escape_markers

# Deterministic band ceilings (a missing required element or a present misconception means the
# explanation cannot be graded "solid"). Applied as a CEILING, not a subtraction, so the LLM's
# band and the rules can never disagree into an arbitrary float.
_OMISSION_CEIL = 0.70
_MISCONCEPTION_CEIL = 0.50
_NO_MECHANISM_CEIL = 0.50  # the illusion-of-competence cap

# The assessment kinds whose grade writes the concept's KnowledgeEstimate (in assess_concept,
# below). Their callers: the /assess route (self_explanation, calibration, source_quiz),
# decay.grade_decay_check (recall), roleplay.grade_roleplay (roleplay),
# paper_probe.grade_paper_probe (paper_probe). The stored estimate is the concept's GRADE only when at least one of these
# exists: the curriculum seeds every concept with a prior (level "high"), and a prior is not a
# grade. Kinds that never write the estimate, and so never make it a grade:
#   teach, productive_failure  (their own engines; corroborating signals, not grades)
#   artifact_review            (the "shipped" signal: engine/artifact.py writes it per phase
#                               concept without touching the estimate, and assess_concept
#                               below skips the estimate for it too, so one high-scoring
#                               review can't be both the grade and its own corroboration)
GRADING_KINDS = frozenset(
    {"self_explanation", "calibration", "source_quiz", "recall", "roleplay", "paper_probe"})
ASSESSABLE_KINDS = GRADING_KINDS | {"artifact_review"}  # what assess_concept accepts


def graded_concept_ids(session: Session, concept_ids: list[int]) -> set[int]:
    """The concepts (of these) whose stored KnowledgeEstimate is a real grade: at least one
    assessment of a GRADING_KINDS kind. Every other concept's estimate is only a prior."""
    if not concept_ids:
        return set()
    return set(session.exec(
        select(Assessment.concept_id).where(
            col(Assessment.concept_id).in_(concept_ids),
            col(Assessment.kind).in_(GRADING_KINDS),
        ).distinct()).all())


class AnchorError(Exception):
    """No ReferenceAnchor available for a source_quiz probe (route maps to HTTP 400)."""


class AssessKindError(ValueError):
    """An assessment kind assess_concept doesn't grade (route maps to HTTP 400)."""


def level_from_score(score: float) -> tuple[str, float]:
    """Map an anchored score (0..1) to a KnowledgeEstimate level + confidence.

    Thresholds are empirical (tune here): >=0.75 high, >=0.45 medium, else low.
    """
    s = max(0.0, min(1.0, score))
    level = "high" if s >= 0.75 else "medium" if s >= 0.45 else "low"
    return level, round(s, 2)


def compute_delta(score: float, baseline_score: float | None) -> float | None:
    if baseline_score is None:
        return None
    return round(score - baseline_score, 4)


def apply_rules_checks(response: str, must_include: list[str], weak_signs: list[str]) -> list[str]:
    """Deterministic anchor checks (§2.3): the LLM grader cannot paper over these."""
    text = response.lower()
    gaps: list[str] = []
    for term in must_include:
        if term and term.lower() not in text:
            gaps.append(f"omitted required element: {term}")
    for sign in weak_signs:
        if sign and sign.lower() in text:
            gaps.append(f"contains likely misconception: {sign}")
    return gaps


def penalize_score(llm_score: float, rules_gaps: list[str]) -> float:
    """Apply deterministic anti-sycophancy CEILINGS (not subtractions): a missing required
    element caps the grade at 'developing-with-gaps'; a present misconception caps it lower."""
    s = max(0.0, min(1.0, llm_score))
    if any(g.startswith("omitted required element") for g in rules_gaps):
        s = min(s, _OMISSION_CEIL)
    if any(g.startswith("contains likely misconception") for g in rules_gaps):
        s = min(s, _MISCONCEPTION_CEIL)
    return round(s, 4)


@dataclass
class RubricDraft:
    criteria: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    strong_signs: list[str] = field(default_factory=list)
    weak_signs: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)


@dataclass
class GradeDraft:
    score: float = 0.0
    verdict: str = ""
    gaps: list[str] = field(default_factory=list)
    confidence_actual: float | None = None
    # The grader's self-report of whether a real causal mechanism was demonstrated. Defaults
    # True so an older/absent value never wrongly caps; a false value triggers the 0.50 cap.
    mechanism_present: bool = True



def _as_float(v, default: float | None) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_rubric_json(text: str) -> RubricDraft:
    d = json.loads(extract_json(text))
    return RubricDraft(
        criteria=list(d.get("criteria", []) or []),
        must_include=list(d.get("must_include", []) or []),
        strong_signs=list(d.get("strong_signs", []) or []),
        weak_signs=list(d.get("weak_signs", []) or []),
        source_refs=list(d.get("source_refs", []) or []),
    )


def parse_grade_json(text: str) -> GradeDraft:
    d = json.loads(extract_json(text))
    return GradeDraft(
        score=_as_float(d.get("score"), 0.0) or 0.0,
        verdict=str(d.get("verdict", "")),
        gaps=list(d.get("gaps", []) or []),
        confidence_actual=_as_float(d.get("confidence_actual"), None),
        mechanism_present=bool(d.get("mechanism_present", True)),
    )


def build_rubric_prompt(concept_name: str, foundation: TopicFoundation | None,
                        sources: list[SourceDoc]) -> tuple[str, str]:
    lines = [f"CONCEPT: {concept_name}"]
    if foundation:
        lines.append(f"FOUNDATION OVERVIEW: {foundation.overview}")
        lines.append(f"KEY CONCEPTS: {', '.join(foundation.key_concepts)}")
    if sources:
        lines.append("SOURCES:")
        for s in sources:
            lines.append(f"- [{s.tier}] {s.title} — {s.summary}".rstrip(" —"))
    return RUBRIC, "\n".join(lines)


def ensure_rubric(session: Session, concept: Concept, *, llm: LLMClient) -> Rubric:
    """Get the concept's rubric, generating + caching it on first use (§2.1)."""
    from adaptive_academy.engine.memory import topic_id_for_concept

    existing = session.exec(select(Rubric).where(Rubric.concept_id == concept.id)).first()
    if existing is not None:
        return existing
    topic_id = topic_id_for_concept(session, concept.id)
    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)).first()
    sources = session.exec(
        select(SourceDoc).where(SourceDoc.topic_id == topic_id,
                                SourceDoc.status == "accepted")).all()
    system, user = build_rubric_prompt(concept.name, foundation, sources)
    resp = llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[])
    draft = parse_rubric_json(resp.text)
    rubric = Rubric(concept_id=concept.id, criteria=draft.criteria,
                    must_include=draft.must_include, strong_signs=draft.strong_signs,
                    weak_signs=draft.weak_signs, source_refs=draft.source_refs)
    session.add(rubric)
    session.commit()
    session.refresh(rubric)
    return rubric


@dataclass
class AssessmentResult:
    assessment: Assessment
    estimate: KnowledgeEstimate | None  # None for a kind outside GRADING_KINDS (no grade)
    events: list[AgentEvent]


def build_grade_prompt(concept_name: str, kind: str, criteria: list[str],
                       reference: str, response: str) -> tuple[str, str]:
    lines = [f"CONCEPT: {concept_name}", f"PROBE KIND: {kind}", "", "RUBRIC / ANCHOR:"]
    for c in criteria:
        lines.append(f"- {c}")
    if reference:
        lines.append(f"REFERENCE ANSWER: {reference}")
    lines += ["", "<<<RESPONSE>>>", escape_markers(response or "(empty)"), "<<<END_RESPONSE>>>"]
    return GRADE, "\n".join(lines)


def _deliverable_criteria(session: Session, item_id: int | None) -> list[str]:
    if item_id is None:
        return []
    item = session.get(Item, item_id)
    if item is None:
        return []
    d = session.exec(select(Deliverable).where(Deliverable.phase_id == item.phase_id)).first()
    return d.acceptance_criteria if d else []


def _resolve_anchor(session: Session, concept: Concept,
                    anchor_id: int | None) -> ReferenceAnchor:
    if anchor_id is not None:
        anchor = session.get(ReferenceAnchor, anchor_id)
        # Don't let a caller grade one concept against another concept's anchor.
        # A topic-wide anchor (concept_id is None) is allowed for any concept.
        if anchor is not None and anchor.concept_id not in (None, concept.id):
            raise AnchorError("anchor belongs to a different concept")
    else:
        anchor = session.exec(
            select(ReferenceAnchor).where(ReferenceAnchor.concept_id == concept.id)
            .order_by(ReferenceAnchor.id)).first()
    if anchor is None:
        raise AnchorError("no anchor for this concept; generate anchors first")
    return anchor


def assess_concept(
    session: Session,
    concept: Concept,
    kind: str,
    response: str,
    *,
    llm: LLMClient,
    confidence_predicted: float | None = None,
    baseline_id: int | None = None,
    item_id: int | None = None,
    anchor_id: int | None = None,
    retriever: Retriever | None = None,
) -> AssessmentResult:
    """Run an anchored probe, persist an Assessment, and (for GRADING_KINDS) update the
    KnowledgeEstimate."""
    from adaptive_academy.engine.memory import index_assessment, topic_id_for_concept

    if kind not in ASSESSABLE_KINDS:
        raise AssessKindError(
            f"unknown assessment kind {kind!r}; expected one of {sorted(ASSESSABLE_KINDS)}")

    events: list[AgentEvent] = []
    topic_id = topic_id_for_concept(session, concept.id)

    def emit(k: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic_id, kind=k, detail=detail)
        session.add(ev)
        events.append(ev)

    # Resolve the anchor (rubric vs. acceptance criteria) and the probe text.
    rubric_id: int | None = None
    anchor_ref_id: int | None = None
    must_include: list[str] = []
    weak_signs: list[str] = []
    reference = ""
    if kind == "artifact_review":
        criteria = _deliverable_criteria(session, item_id)
        probe = PROBE_TEXT[kind].format(concept=concept.name)
    elif kind == "source_quiz":
        anchor = _resolve_anchor(session, concept, anchor_id)
        anchor_ref_id = anchor.id
        criteria = anchor.key_points
        must_include = anchor.key_points
        reference = anchor.reference_answer
        probe = anchor.question
    else:
        rubric = ensure_rubric(session, concept, llm=llm)
        rubric_id = rubric.id
        criteria, must_include, weak_signs = rubric.criteria, rubric.must_include, rubric.weak_signs
        probe = PROBE_TEXT.get(kind, PROBE_TEXT["self_explanation"]).format(
            concept=concept.name, question=concept.name)
    emit("assess:probe", kind)

    emit("prompt", GRADE.tag)
    system, user = build_grade_prompt(concept.name, kind, criteria, reference, response)
    grade = parse_grade_json(
        llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[]).text)

    rules_gaps = apply_rules_checks(response, must_include, weak_signs)
    if rules_gaps:
        emit("assess:rules", f"{len(rules_gaps)} hard gap(s)")
    # Code-enforced illusion-of-competence cap: fluent prose with no demonstrated mechanism
    # cannot score above 'developing', no matter what the LLM returned (defense in depth).
    score = grade.score
    if not grade.mechanism_present:
        score = min(score, _NO_MECHANISM_CEIL)
        emit("assess:mechanism", "capped: no mechanism demonstrated")
    final_score = penalize_score(score, rules_gaps)
    gaps = list(grade.gaps) + rules_gaps
    emit("assess:graded", f"score={final_score}")

    baseline = session.get(Assessment, baseline_id) if baseline_id else None
    delta = compute_delta(final_score, baseline.score if baseline else None)
    confidence_actual = final_score if kind == "calibration" else grade.confidence_actual

    assessment = Assessment(
        concept_id=concept.id, item_id=item_id, kind=kind, prompt=probe, response=response,
        verdict=grade.verdict, score=final_score, gaps=gaps,
        confidence_predicted=confidence_predicted, confidence_actual=confidence_actual,
        rubric_id=rubric_id, anchor_id=anchor_ref_id,
        baseline_assessment_id=baseline_id, delta=delta)
    session.add(assessment)
    session.flush()
    index_assessment(session, assessment, topic_id=topic_id, retriever=retriever)

    estimate: KnowledgeEstimate | None = None
    if kind in GRADING_KINDS:
        level, conf = level_from_score(final_score)
        estimate = session.exec(
            select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept.id)).first()
        if estimate is None:
            estimate = KnowledgeEstimate(concept_id=concept.id)
            session.add(estimate)
        estimate.level, estimate.confidence = level, conf
        emit("assess:estimate", f"level={level}")

    emit("assess:done", f"concept {concept.id}")
    session.commit()
    session.refresh(assessment)
    if estimate is not None:
        session.refresh(estimate)
    return AssessmentResult(assessment=assessment, estimate=estimate, events=events)
