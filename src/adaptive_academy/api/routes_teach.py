from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import TeachIn, TeachOut
from adaptive_academy.engine.teach import grade_teaching
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Concept

router = APIRouter(prefix="/api/concepts", tags=["teach"])


@router.post("/{concept_id}/teach", response_model=TeachOut)
def teach(concept_id: int, body: TeachIn, session: Session = Depends(get_session),
          llm: LLMClient = Depends(get_llm)) -> TeachOut:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    result = grade_teaching(session, concept, body.explanation, llm=llm)
    return TeachOut(score=result.score, feedback=result.feedback,
                    strengths=result.strengths, gaps=result.gaps)
