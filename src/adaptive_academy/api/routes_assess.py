from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_llm, get_retriever, get_session
from adaptive_academy.api.schemas import AssessIn, AssessmentOut, RubricOut
from adaptive_academy.engine.assess import AnchorError, assess_concept, ensure_rubric
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Assessment, Concept

router = APIRouter(prefix="/api/concepts", tags=["assess"])


def _assessment_out(a: Assessment, level: str | None = None) -> AssessmentOut:
    return AssessmentOut(
        id=a.id, kind=a.kind, prompt=a.prompt, response=a.response, verdict=a.verdict,
        score=a.score, gaps=a.gaps, confidence_predicted=a.confidence_predicted,
        confidence_actual=a.confidence_actual, delta=a.delta, estimate_level=level)


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
                                anchor_id=body.anchor_id)
    except AnchorError as e:
        raise HTTPException(400, str(e))
    # Engaging with a concept arms a delayed, unassisted retrieval check (§8.6).
    # A decay-check recall is itself rescheduled inside grade_decay_check, so skip re-arming.
    if body.kind != "recall":
        from adaptive_academy.engine.decay import schedule_decay_check
        schedule_decay_check(session, concept_id, retriever=retriever)
    return _assessment_out(result.assessment, result.estimate.level)


@router.get("/{concept_id}/assessments", response_model=list[AssessmentOut])
def list_assessments(concept_id: int, session: Session = Depends(get_session)) -> list[AssessmentOut]:
    rows = session.exec(
        select(Assessment).where(Assessment.concept_id == concept_id)
        .order_by(Assessment.id.desc())).all()
    return [_assessment_out(a) for a in rows]


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
