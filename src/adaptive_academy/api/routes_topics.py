from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_session
from adaptive_academy.api.schemas import ConceptOut, TopicOut
from adaptive_academy.models import Concept, Topic, Track

router = APIRouter(prefix="/api/topics", tags=["topics"])


def _concepts_for(session: Session, topic_id: int) -> list[Concept]:
    return session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)
    ).all()


@router.get("", response_model=list[TopicOut])
def list_topics(session: Session = Depends(get_session)):
    return [
        _to_out(topic, _concepts_for(session, topic.id))
        for topic in session.exec(select(Topic)).all()
    ]


@router.get("/{topic_id}", response_model=TopicOut)
def get_topic(topic_id: int, session: Session = Depends(get_session)):
    topic = session.get(Topic, topic_id)
    if not topic:
        raise HTTPException(404, "topic not found")
    return _to_out(topic, _concepts_for(session, topic_id))


def _to_out(topic: Topic, concepts: list[Concept]) -> TopicOut:
    return TopicOut(
        id=topic.id,
        title=topic.title,
        concepts=[
            ConceptOut(id=c.id, name=c.name, is_load_bearing=c.is_load_bearing)
            for c in concepts
        ],
    )
