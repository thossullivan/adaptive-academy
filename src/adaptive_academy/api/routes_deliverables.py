from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import ArtifactReviewOut, ShipIn
from adaptive_academy.engine.artifact import review_artifact
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Deliverable

router = APIRouter(prefix="/api/deliverables", tags=["deliverables"])


@router.post("/{deliverable_id}/ship", response_model=ArtifactReviewOut)
def ship(
    deliverable_id: int,
    body: ShipIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
) -> ArtifactReviewOut:
    deliverable = session.get(Deliverable, deliverable_id)
    if deliverable is None:
        raise HTTPException(404, "deliverable not found")
    result = review_artifact(session, deliverable, body.artifact_url, body.content, llm=llm)
    return ArtifactReviewOut(
        score=result.score, verdict=result.verdict, gaps=result.gaps, concepts=result.concepts)
