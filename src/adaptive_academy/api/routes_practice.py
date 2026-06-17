from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import ChallengeOut, ConsolidateIn, ConsolidateOut
from adaptive_academy.engine.productive_failure import consolidate, generate_challenge
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Concept

router = APIRouter(prefix="/api/concepts", tags=["practice"])


@router.post("/{concept_id}/productive_failure/generate", response_model=ChallengeOut)
def generate(concept_id: int, session: Session = Depends(get_session),
             llm: LLMClient = Depends(get_llm)) -> ChallengeOut:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    return ChallengeOut(problem=generate_challenge(session, concept, llm=llm))


@router.post("/{concept_id}/productive_failure/consolidate", response_model=ConsolidateOut)
def do_consolidate(concept_id: int, body: ConsolidateIn,
                   session: Session = Depends(get_session),
                   llm: LLMClient = Depends(get_llm)) -> ConsolidateOut:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    result = consolidate(session, concept, body.problem, body.attempt, llm=llm)
    return ConsolidateOut(canonical=result.canonical, feedback=result.feedback,
                          score=result.score)
