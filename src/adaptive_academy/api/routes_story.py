from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import EventOut, StoryOut
from adaptive_academy.engine.story import StoryError, gather_story_facts, generate_story
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Topic

router = APIRouter(prefix="/api/topics", tags=["story"])


@router.get("/{topic_id}/story/facts")
def story_facts(topic_id: int, session: Session = Depends(get_session)) -> dict:
    """The deterministic numbers a story is grounded in — no model call, so the Story page can
    show them before (or without) composing the narrative."""
    try:
        return gather_story_facts(session, topic_id).to_dict()
    except StoryError as e:
        raise HTTPException(404, str(e))


@router.post("/{topic_id}/story", response_model=StoryOut)
def make_story(
    topic_id: int,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
) -> StoryOut:
    if session.get(Topic, topic_id) is None:
        raise HTTPException(404, "topic not found")
    try:
        result = generate_story(session, topic_id, llm=llm)
    except StoryError as e:
        raise HTTPException(404, str(e))
    return StoryOut(
        headline=result.headline,
        narrative=result.narrative,
        highlights=result.highlights,
        facts=result.facts.to_dict(),
        events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events],
    )
