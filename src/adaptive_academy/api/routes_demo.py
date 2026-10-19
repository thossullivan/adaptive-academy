"""One-click demo topic: add it to explore the app without an API key, remove it as a unit.

Neither route depends on an LLM client: the demo is built from fixed content in code.
"""

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlmodel import Session

from adaptive_academy.api.deps import get_session
from adaptive_academy.demo import ensure_demo, remove_demo

router = APIRouter(prefix="/api/demo", tags=["demo"])


class DemoOut(BaseModel):
    topic_id: int
    created: bool


@router.post("", response_model=DemoOut)
def create_demo(session: Session = Depends(get_session)) -> DemoOut:
    """Create the demo topic if there is none; either way, return its id."""
    topic, created = ensure_demo(session)
    return DemoOut(topic_id=topic.id, created=created)


@router.delete("", status_code=204)
def delete_demo(session: Session = Depends(get_session)) -> Response:
    """Delete the demo topic and every row that belongs to it."""
    if not remove_demo(session):
        raise HTTPException(404, "no demo topic")
    return Response(status_code=204)
