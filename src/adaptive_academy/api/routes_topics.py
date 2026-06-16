from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_session
from adaptive_academy.api.schemas import (
    ConceptOut,
    CreateTopicIn,
    FoundationOut,
    IntentOut,
    TopicOut,
)
from adaptive_academy.models import Concept, Topic, TopicFoundation, TopicIntent, Track

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
