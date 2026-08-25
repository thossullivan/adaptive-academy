"""Read-only concept graph routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, col, select

from adaptive_academy.api.deps import get_session
from adaptive_academy.api.schemas import ConceptOut, EdgeOut, GraphOut
from adaptive_academy.engine import graph
from adaptive_academy.models import (
    Assessment,
    Concept,
    ConceptEdge,
    ReferenceAnchor,
    Topic,
    Track,
)

router = APIRouter(tags=["graph"])


def _concept_out(session: Session, concept: Concept) -> ConceptOut:
    has_anchor = session.exec(
        select(ReferenceAnchor).where(ReferenceAnchor.concept_id == concept.id)
    ).first() is not None
    last_assessment_score = session.exec(
        select(Assessment.score)
        .where(Assessment.concept_id == concept.id)
        .order_by(Assessment.id.desc())
    ).first()
    return ConceptOut(
        id=concept.id,
        name=concept.name,
        is_load_bearing=concept.is_load_bearing,
        last_assessment_score=last_assessment_score,
        has_anchor=has_anchor,
    )


def _require_concept(session: Session, concept_id: int) -> Concept:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    return concept


@router.get("/api/topics/{topic_id}/graph", response_model=GraphOut)
def topic_graph(
    topic_id: int,
    session: Session = Depends(get_session),
) -> GraphOut:
    if session.get(Topic, topic_id) is None:
        raise HTTPException(404, "topic not found")
    concepts = session.exec(
        select(Concept)
        .join(Track)
        .where(Track.topic_id == topic_id)
        .order_by(Concept.id)
    ).all()
    concept_ids = [concept.id for concept in concepts if concept.id is not None]
    edges = []
    if concept_ids:
        edges = session.exec(
            select(ConceptEdge)
            .where(
                ConceptEdge.src_concept_id.in_(concept_ids),
                ConceptEdge.dst_concept_id.in_(concept_ids),
                col(ConceptEdge.valid_until).is_(None),
            )
            .order_by(ConceptEdge.id)
        ).all()
    return GraphOut(
        nodes=[_concept_out(session, concept) for concept in concepts],
        edges=[
            EdgeOut(
                src=edge.src_concept_id,
                dst=edge.dst_concept_id,
                kind=edge.kind,
                weight=edge.weight,
            )
            for edge in edges
        ],
    )


@router.get(
    "/api/concepts/{concept_id}/ancestors",
    response_model=list[tuple[int, int]],
)
def concept_ancestors(
    concept_id: int,
    depth: int = graph.DEFAULT_TRAVERSAL_DEPTH,
    session: Session = Depends(get_session),
) -> list[tuple[int, int]]:
    _require_concept(session, concept_id)
    return graph.ancestors(session, concept_id, max_depth=depth)


@router.get("/api/concepts/{concept_id}/neighbors", response_model=list[int])
def concept_neighbors(
    concept_id: int,
    session: Session = Depends(get_session),
) -> list[int]:
    _require_concept(session, concept_id)
    return graph.neighbors(session, concept_id)
