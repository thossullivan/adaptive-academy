from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from adaptive_academy.api.deps import get_llm, get_retriever, get_session
from adaptive_academy.api.schemas import AssessIn, AssessmentOut, RubricOut
from adaptive_academy.engine.assess import (
    AnchorError,
    AssessKindError,
    assess_concept,
    ensure_rubric,
    graded_concept_ids,
)
from adaptive_academy.engine import scout
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    KnowledgeEstimate,
    Milestone,
    ProgramTopicLink,
    Track,
)

router = APIRouter(prefix="/api/concepts", tags=["assess"])


def _assessment_out(a: Assessment, level: str | None = None) -> AssessmentOut:
    return AssessmentOut(
        id=a.id, kind=a.kind, prompt=a.prompt, response=a.response, verdict=a.verdict,
        score=a.score, gaps=a.gaps, confidence_predicted=a.confidence_predicted,
        confidence_actual=a.confidence_actual, delta=a.delta, estimate_level=level)


def _program_id_for_concept(session: Session, concept: Concept) -> int | None:
    track = session.get(Track, concept.track_id)
    if track is None:
        return None
    return session.exec(
        select(Milestone.program_id)
        .join(
            ProgramTopicLink,
            ProgramTopicLink.milestone_id == Milestone.id,
        )
        .where(
            ProgramTopicLink.topic_id == track.topic_id,
            ProgramTopicLink.status == "started",
            col(Milestone.archived).is_(False),
        )
        .order_by(Milestone.id)
    ).first()


def _maybe_scout_after_assessment(
    session: Session,
    concept: Concept,
    *,
    llm: LLMClient,
) -> None:
    program_id = _program_id_for_concept(session, concept)
    if program_id is None:
        return
    try:
        scout.maybe_scout(session, program_id, llm=llm)
    except Exception as exc:
        session.rollback()
        try:
            session.add(
                AgentEvent(
                    program_id=program_id,
                    kind="scout:error",
                    detail=f"{type(exc).__name__}: {exc}"[:400],
                )
            )
            session.commit()
        except Exception:
            session.rollback()


@router.post("/{concept_id}/assess", response_model=AssessmentOut)
def assess(concept_id: int, body: AssessIn, session: Session = Depends(get_session),
           llm: LLMClient = Depends(get_llm),
           retriever: Retriever = Depends(get_retriever)) -> AssessmentOut:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    try:
        result = assess_concept(session, concept, body.kind, body.response, llm=llm,
                                confidence_predicted=body.confidence_predicted,
                                baseline_id=body.baseline_id, item_id=body.item_id,
                                anchor_id=body.anchor_id, retriever=retriever)
    except (AnchorError, AssessKindError) as e:
        raise HTTPException(400, str(e))
    # Engaging with a concept arms a delayed, unassisted retrieval check (§8.6).
    # A decay-check recall is itself rescheduled inside grade_decay_check, so skip re-arming.
    if body.kind != "recall":
        from adaptive_academy.engine.decay import schedule_decay_check
        schedule_decay_check(session, concept_id, retriever=retriever)
    _maybe_scout_after_assessment(session, concept, llm=llm)
    return _assessment_out(result.assessment,
                           result.estimate.level if result.estimate else None)


@router.get("/{concept_id}/assessments", response_model=list[AssessmentOut])
def list_assessments(concept_id: int, session: Session = Depends(get_session)) -> list[AssessmentOut]:
    rows = session.exec(
        select(Assessment).where(Assessment.concept_id == concept_id)
        .order_by(Assessment.id.desc())).all()
    # The competence grade is the concept's STORED estimate (written by the Assessor), carried
    # on the newest row only; it is never recomputed from a row's own score. It counts as a
    # grade only once an assessment of a kind that writes it exists (assess.GRADING_KINDS);
    # until then the estimate is just the curriculum's prior, which is not a grade.
    level = None
    if graded_concept_ids(session, [concept_id]):
        estimate = session.exec(
            select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept_id)
        ).first()
        level = estimate.level if estimate else None
    return [_assessment_out(a, level if i == 0 else None) for i, a in enumerate(rows)]


@router.get("/{concept_id}/rubric", response_model=RubricOut)
def get_rubric(concept_id: int, session: Session = Depends(get_session),
               llm: LLMClient = Depends(get_llm)) -> RubricOut:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    r = ensure_rubric(session, concept, llm=llm)
    return RubricOut(id=r.id, concept_id=r.concept_id, criteria=r.criteria,
                     must_include=r.must_include, strong_signs=r.strong_signs,
                     weak_signs=r.weak_signs, reviewed_by_user=r.reviewed_by_user)
