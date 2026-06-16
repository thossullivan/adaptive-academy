from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.api.schemas import (
    ConceptOut,
    CreateTopicIn,
    EventOut,
    FoundationOut,
    IntentOut,
    ResearchOut,
    ReviewSourcesIn,
    SourceDocOut,
    TopicOut,
)
from adaptive_academy.engine.research import research_topic
from adaptive_academy.llm.researcher_types import ResearcherClient
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Concept,
    SourceDoc,
    Topic,
    TopicFoundation,
    TopicIntent,
    Track,
)

router = APIRouter(prefix="/api/topics", tags=["topics"])


def _concepts_for(session: Session, topic_id: int) -> list[Concept]:
    return session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)
    ).all()


def _topic_out(session: Session, topic: Topic) -> TopicOut:
    concepts = _concepts_for(session, topic.id)
    intent = session.exec(
        select(TopicIntent).where(TopicIntent.topic_id == topic.id)
    ).first()
    has_foundation = (
        session.exec(
            select(TopicFoundation).where(TopicFoundation.topic_id == topic.id)
        ).first()
        is not None
    )
    return TopicOut(
        id=topic.id,
        title=topic.title,
        concepts=[
            ConceptOut(id=c.id, name=c.name, is_load_bearing=c.is_load_bearing)
            for c in concepts
        ],
        intent=IntentOut(
            goal=intent.goal,
            prior_knowledge=intent.prior_knowledge,
            time_budget=intent.time_budget,
        )
        if intent
        else None,
        has_foundation=has_foundation,
    )


@router.get("", response_model=list[TopicOut])
def list_topics(session: Session = Depends(get_session)):
    return [_topic_out(session, topic) for topic in session.exec(select(Topic)).all()]


@router.post("", response_model=TopicOut)
def create_topic(
    body: CreateTopicIn, session: Session = Depends(get_session)
) -> TopicOut:
    topic = Topic(title=body.title)
    session.add(topic)
    session.commit()
    session.refresh(topic)
    session.add(
        TopicIntent(
            topic_id=topic.id,
            goal=body.goal,
            prior_knowledge=body.prior_knowledge,
            time_budget=body.time_budget,
        )
    )
    session.commit()
    return _topic_out(session, topic)


@router.get("/{topic_id}", response_model=TopicOut)
def get_topic(topic_id: int, session: Session = Depends(get_session)):
    topic = session.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "topic not found")
    return _topic_out(session, topic)


@router.get("/{topic_id}/foundation", response_model=FoundationOut)
def get_foundation(
    topic_id: int, session: Session = Depends(get_session)
) -> FoundationOut:
    fnd = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)
    ).first()
    if fnd is None:
        raise HTTPException(status_code=404, detail="no foundation yet")
    return FoundationOut(
        overview=fnd.overview,
        key_concepts=fnd.key_concepts,
        prerequisite_map=fnd.prerequisite_map,
    )


def _source_out(s: SourceDoc) -> SourceDocOut:
    return SourceDocOut(
        id=s.id, title=s.title, url=s.url, tier=s.tier, summary=s.summary,
        why=s.why, rank=s.rank, angle=s.angle, status=s.status,
    )


@router.post("/{topic_id}/research", response_model=ResearchOut)
def run_research(
    topic_id: int,
    session: Session = Depends(get_session),
    researcher: ResearcherClient = Depends(get_researcher),
    llm: LLMClient = Depends(get_llm),
) -> ResearchOut:
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise HTTPException(status_code=404, detail="topic not found")
    intent = session.exec(select(TopicIntent).where(TopicIntent.topic_id == topic_id)).first()
    if intent is None:
        raise HTTPException(status_code=400, detail="topic has no intent")

    result = research_topic(session, topic, intent, researcher=researcher, llm=llm)
    return ResearchOut(
        foundation=FoundationOut(
            overview=result.foundation.overview,
            key_concepts=result.foundation.key_concepts,
            prerequisite_map=result.foundation.prerequisite_map,
        ),
        sources=[_source_out(s) for s in sorted(result.sources, key=lambda x: x.rank)],
        events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events],
    )


@router.get("/{topic_id}/events", response_model=list[EventOut])
def list_events(
    topic_id: int,
    session: Session = Depends(get_session),
) -> list[EventOut]:
    rows = session.exec(
        select(AgentEvent)
        .where(AgentEvent.topic_id == topic_id)
        .order_by(AgentEvent.id)
    ).all()
    return [EventOut(kind=e.kind, detail=e.detail) for e in rows]


@router.get("/{topic_id}/sources", response_model=list[SourceDocOut])
def list_sources(
    topic_id: int,
    status: Optional[str] = None,
    session: Session = Depends(get_session),
) -> list[SourceDocOut]:
    query = select(SourceDoc).where(SourceDoc.topic_id == topic_id)
    if status is not None:
        query = query.where(SourceDoc.status == status)
    rows = session.exec(query).all()
    rows.sort(key=lambda s: s.rank)
    return [_source_out(s) for s in rows]


@router.post("/{topic_id}/sources/review", response_model=list[SourceDocOut])
def review_sources(
    topic_id: int,
    body: ReviewSourcesIn,
    session: Session = Depends(get_session),
) -> list[SourceDocOut]:
    rows = session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic_id)).all()
    by_id = {s.id: s for s in rows}
    for sid in body.accepted_ids:
        if sid in by_id:
            by_id[sid].status = "accepted"
    for sid in body.pruned_ids:
        if sid in by_id:
            by_id[sid].status = "pruned"
    session.commit()
    for s in rows:
        session.refresh(s)
    rows.sort(key=lambda s: s.rank)
    return [_source_out(s) for s in rows]
