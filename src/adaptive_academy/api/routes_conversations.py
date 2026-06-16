from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import (
    ConversationOut,
    EventOut,
    MessageOut,
    SendMessageIn,
    SendMessageOut,
    StartConversationIn,
)
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.tutor import run_tutor_turn
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Concept, Conversation

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _levels_for(session: Session, convo: Conversation):
    concept = session.get(Concept, convo.concept_id)
    return compute_levels(concept.estimate if concept else None)


@router.post("", response_model=ConversationOut)
def start_conversation(body: StartConversationIn, session: Session = Depends(get_session)):
    convo = Conversation(topic_id=body.topic_id, concept_id=body.concept_id)
    session.add(convo)
    session.commit()
    session.refresh(convo)
    levels = _levels_for(session, convo)
    return ConversationOut(
        id=convo.id,
        concept_id=convo.concept_id,
        attempt_logged=convo.attempt_logged,
        assistance_level=levels.assistance,
        challenge_level=levels.challenge,
        messages=[],
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: int, session: Session = Depends(get_session)):
    convo = session.get(Conversation, conversation_id)
    if not convo:
        raise HTTPException(404, "conversation not found")
    levels = _levels_for(session, convo)
    return ConversationOut(
        id=convo.id,
        concept_id=convo.concept_id,
        attempt_logged=convo.attempt_logged,
        assistance_level=levels.assistance,
        challenge_level=levels.challenge,
        messages=[MessageOut(role=m.role, content=m.content) for m in convo.messages],
    )


@router.post("/{conversation_id}/messages", response_model=SendMessageOut)
def send_message(
    conversation_id: int,
    body: SendMessageIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
):
    convo = session.get(Conversation, conversation_id)
    if not convo:
        raise HTTPException(404, "conversation not found")
    result = run_tutor_turn(session, convo, body.content, llm)
    session.refresh(convo)
    levels = _levels_for(session, convo)
    return SendMessageOut(
        reply=result.reply,
        attempt_logged=convo.attempt_logged,
        assistance_level=levels.assistance,
        challenge_level=levels.challenge,
        events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events],
    )
