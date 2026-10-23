from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from adaptive_academy.api.deps import (
    get_guard_llm,
    get_llm,
    get_retriever,
    get_session,
    use_agent_sdk,
)
from adaptive_academy.api.routes_memory import memory_hit_out
from adaptive_academy.api.schemas import (
    ConversationOut,
    ConversationPreviewOut,
    EventOut,
    MessageOut,
    SendMessageIn,
    SendMessageOut,
    StartConversationIn,
)
from adaptive_academy.engine.levels import compute_levels
from adaptive_academy.engine.tutor import run_tutor_turn
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Attempt, Concept, Conversation, Track

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


def _levels_for(session: Session, convo: Conversation):
    concept = session.get(Concept, convo.concept_id)
    return compute_levels(concept.estimate if concept else None)


def _concept_in_topic(session: Session, topic_id: int, concept_id: int) -> Concept:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    track = session.get(Track, concept.track_id)
    if track is None or track.topic_id != topic_id:
        raise HTTPException(400, "concept does not belong to this topic")
    return concept


@router.post("", response_model=ConversationOut)
def start_conversation(body: StartConversationIn, session: Session = Depends(get_session)):
    _concept_in_topic(session, body.topic_id, body.concept_id)
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


# Declared before "/{conversation_id}" so "preview" is not parsed as an id.
@router.get("/preview", response_model=ConversationPreviewOut)
def preview_conversation(
    topic_id: int = Query(...),
    concept_id: int = Query(...),
    session: Session = Depends(get_session),
):
    """What a new session on this concept would start with, without saving one.

    The Tutor shows this before the first message; the conversation row is created
    only when the learner sends something. A new session never has an attempt logged.
    """
    concept = _concept_in_topic(session, topic_id, concept_id)
    levels = compute_levels(concept.estimate)
    return ConversationPreviewOut(
        concept_id=concept.id,
        attempt_logged=False,
        assistance_level=levels.assistance,
        challenge_level=levels.challenge,
    )


@router.get("/{conversation_id}", response_model=ConversationOut)
def get_conversation(conversation_id: int, session: Session = Depends(get_session)):
    convo = session.get(Conversation, conversation_id)
    if not convo:
        raise HTTPException(404, "conversation not found")
    levels = _levels_for(session, convo)
    # Each submitted attempt's verdict, so a reload still tells a rejected one apart. Rows in
    # id order: should a message ever have two, the latest wins.
    verdicts = {a.message_id: a.accepted for a in session.exec(
        select(Attempt).where(Attempt.conversation_id == convo.id).order_by(Attempt.id))}
    return ConversationOut(
        id=convo.id,
        concept_id=convo.concept_id,
        attempt_logged=convo.attempt_logged,
        assistance_level=levels.assistance,
        challenge_level=levels.challenge,
        messages=[MessageOut(role=m.role, content=m.content, is_attempt=bool(m.is_attempt),
                             attempt_accepted=verdicts.get(m.id),
                             reveals_solution=bool(m.reveals_solution))
                  for m in convo.messages],
    )


@router.post("/{conversation_id}/messages", response_model=SendMessageOut)
def send_message(
    conversation_id: int,
    body: SendMessageIn,
    session: Session = Depends(get_session),
    llm: LLMClient = Depends(get_llm),
    retriever: Retriever = Depends(get_retriever),
    guard_llm: LLMClient = Depends(get_guard_llm),
):
    convo = session.get(Conversation, conversation_id)
    if not convo:
        raise HTTPException(404, "conversation not found")
    if use_agent_sdk():
        # Subscription tutor: SDK in-process tool + code-enforced attempt-gate (no API key).
        from adaptive_academy.engine.tutor_sdk import run_tutor_turn_sdk
        result = run_tutor_turn_sdk(
            session,
            convo,
            body.content,
            retriever=retriever,
            guard_llm=guard_llm,
            attempt=body.attempt,
        )
    else:
        result = run_tutor_turn(
            session,
            convo,
            body.content,
            llm,
            retriever=retriever,
            guard_llm=guard_llm,
            attempt=body.attempt,
        )
    session.refresh(convo)
    levels = _levels_for(session, convo)
    return SendMessageOut(
        reply=result.reply,
        attempt_logged=convo.attempt_logged,
        attempt_outcome=result.attempt_outcome,
        reveals_solution=result.reveals_solution,
        assistance_level=levels.assistance,
        challenge_level=levels.challenge,
        events=[EventOut(kind=e.kind, detail=e.detail) for e in result.events],
        memory=[memory_hit_out(hit) for hit in result.memory],
    )
