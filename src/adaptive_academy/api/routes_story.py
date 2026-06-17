from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import EventOut, StoryOut
from adaptive_academy.engine.story import StoryError, generate_story
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Topic

router = APIRouter(prefix="/api/topics", tags=["story"])


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
