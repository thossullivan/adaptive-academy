from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_llm, get_retriever, get_session
from adaptive_academy.api.schemas import (
    DecayDueOut,
    DecayGradeIn,
    DecayGradeOut,
    DecayItemOut,
)
from adaptive_academy.engine.decay import due_decay_checks, grade_decay_check
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Concept

topic_router = APIRouter(prefix="/api/topics", tags=["decay"])
ops_router = APIRouter(prefix="/api/decay", tags=["decay"])


@topic_router.get("/{topic_id}/decay", response_model=DecayDueOut)
def list_due(topic_id: int, session: Session = Depends(get_session)) -> DecayDueOut:
    items = []
    for p in due_decay_checks(session, topic_id):
        concept = session.get(Concept, p.concept_id)
        items.append(DecayItemOut(
            prompt_id=p.id, concept_id=p.concept_id,
            concept_name=concept.name if concept else "", prompt=p.prompt,
            last_result=p.last_result))
    return DecayDueOut(items=items)


@ops_router.post("/{prompt_id}/grade", response_model=DecayGradeOut)
def grade(prompt_id: int, body: DecayGradeIn, session: Session = Depends(get_session),
          llm: LLMClient = Depends(get_llm),
          retriever: Retriever = Depends(get_retriever)) -> DecayGradeOut:
    try:
        result = grade_decay_check(
            session,
            prompt_id,
            body.response,
            llm=llm,
            retriever=retriever,
        )
    except ValueError as e:
        raise HTTPException(404, str(e))
    a = result.assessment
    from adaptive_academy.engine.assess import level_from_score
    level, _ = level_from_score(a.score)
    return DecayGradeOut(
        recall_score=result.recall_score, baseline_score=result.baseline_score,
        decay_delta=result.decay_delta, held=result.held, verdict=a.verdict,
        gaps=a.gaps, estimate_level=level)
