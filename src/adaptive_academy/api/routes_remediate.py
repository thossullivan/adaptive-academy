from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import EventOut, ItemOut, RemediateIn, RemediationOut
from adaptive_academy.engine.remediate import RemediationError, remediate_concept
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Concept, Item

router = APIRouter(prefix="/api/concepts", tags=["remediate"])


def _item_out(i: Item) -> ItemOut:
    return ItemOut(id=i.id, text=i.text, type=i.type, status=i.status,
                   position=i.position, is_remediation=i.added_by == "remediation")


@router.post("/{concept_id}/remediate", response_model=RemediationOut)
def remediate(concept_id: int, body: RemediateIn,
              session: Session = Depends(get_session),
              llm: LLMClient = Depends(get_llm)) -> RemediationOut:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    try:
        result = remediate_concept(session, concept, llm=llm,
                                   assessment_id=body.from_assessment_id)
    except RemediationError as e:
        raise HTTPException(400, str(e))
    return RemediationOut(items=[_item_out(i) for i in result.items],
                          events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events])
