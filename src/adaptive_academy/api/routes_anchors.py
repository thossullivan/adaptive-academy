from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_anchor_client, get_session
from adaptive_academy.api.schemas import AnchorGenOut, AnchorOut, EventOut
from adaptive_academy.engine.anchors import AnchorGenError, generate_anchors
from adaptive_academy.llm.anchor_types import AnchorClient
from adaptive_academy.models import ReferenceAnchor, SourceDoc, Topic

topic_router = APIRouter(prefix="/api/topics", tags=["anchors"])
concept_router = APIRouter(prefix="/api/concepts", tags=["anchors"])


def _anchor_out(a: ReferenceAnchor) -> AnchorOut:
    return AnchorOut(id=a.id, source_doc_id=a.source_doc_id, concept_id=a.concept_id,
                     question=a.question, reference_answer=a.reference_answer,
                     key_points=a.key_points)


@topic_router.post("/{topic_id}/anchors", response_model=AnchorGenOut)
def generate(topic_id: int, session: Session = Depends(get_session),
             anchor_client: AnchorClient = Depends(get_anchor_client)) -> AnchorGenOut:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(404, "topic not found")
    try:
        result = generate_anchors(session, topic, anchor_client=anchor_client)
    except AnchorGenError as e:
        raise HTTPException(400, str(e))
    return AnchorGenOut(anchors=[_anchor_out(a) for a in result.anchors],
                        events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events])


@topic_router.get("/{topic_id}/anchors", response_model=list[AnchorOut])
def list_topic_anchors(topic_id: int, concept_id: int | None = None,
                       session: Session = Depends(get_session)) -> list[AnchorOut]:
    q = (select(ReferenceAnchor).join(SourceDoc)
         .where(SourceDoc.topic_id == topic_id))
    if concept_id is not None:
        q = q.where(ReferenceAnchor.concept_id == concept_id)
    return [_anchor_out(a) for a in session.exec(q).all()]


@concept_router.get("/{concept_id}/anchors", response_model=list[AnchorOut])
def list_concept_anchors(concept_id: int,
                         session: Session = Depends(get_session)) -> list[AnchorOut]:
    rows = session.exec(
        select(ReferenceAnchor).where(ReferenceAnchor.concept_id == concept_id)).all()
    return [_anchor_out(a) for a in rows]
