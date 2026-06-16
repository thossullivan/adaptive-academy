from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.api.schemas import (
    CardGradeIn, CardReviewIn, ProposeRetentionIn, RecallPromptOut, RetentionOut, SRSCardOut,
)
from adaptive_academy.engine.retention import grade_card, propose_retention
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    Assessment, Concept, RecallPrompt, SRSCard, Track,
)

card_router = APIRouter(prefix="/api/concepts", tags=["retention"])
topic_router = APIRouter(prefix="/api/topics", tags=["retention"])
ops_router = APIRouter(prefix="/api/retention", tags=["retention"])

_VALID_STATUS = {"active", "suspended"}
_VALID_RESULT = {"again", "hard", "good", "easy"}


def _card_out(c: SRSCard) -> SRSCardOut:
    return SRSCardOut(id=c.id, concept_id=c.concept_id, front=c.front, back=c.back,
                      status=c.status, interval=c.interval, reps=c.reps,
                      last_result=c.last_result)


def _prompt_out(p: RecallPrompt) -> RecallPromptOut:
    return RecallPromptOut(id=p.id, concept_id=p.concept_id, prompt=p.prompt, status=p.status)


@card_router.post("/{concept_id}/retention/propose", response_model=RetentionOut)
def propose(concept_id: int, body: ProposeRetentionIn,
            session: Session = Depends(get_session),
            llm: LLMClient = Depends(get_llm)) -> RetentionOut:
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise HTTPException(404, "concept not found")
    if body.from_assessment_id is not None:
        assessment = session.get(Assessment, body.from_assessment_id)
    else:
        assessment = session.exec(
            select(Assessment).where(Assessment.concept_id == concept_id)
            .order_by(Assessment.id.desc())).first()
    if assessment is None:
        raise HTTPException(400, "no assessment to propose retention from")
    cards, prompts = propose_retention(session, concept, assessment, llm=llm)
    return RetentionOut(cards=[_card_out(c) for c in cards],
                        prompts=[_prompt_out(p) for p in prompts])


@topic_router.get("/{topic_id}/retention", response_model=RetentionOut)
def list_retention(topic_id: int, status: Optional[str] = None,
                   session: Session = Depends(get_session)) -> RetentionOut:
    concept_ids = [c.id for c in session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)).all()]
    if not concept_ids:
        return RetentionOut(cards=[], prompts=[])
    cq = select(SRSCard).where(SRSCard.concept_id.in_(concept_ids))
    pq = select(RecallPrompt).where(RecallPrompt.concept_id.in_(concept_ids))
    if status is not None:
        cq = cq.where(SRSCard.status == status)
        pq = pq.where(RecallPrompt.status == status)
    return RetentionOut(
        cards=[_card_out(c) for c in session.exec(cq).all()],
        prompts=[_prompt_out(p) for p in session.exec(pq).all()])


@ops_router.post("/cards/{card_id}/review", response_model=SRSCardOut)
def review_card(card_id: int, body: CardReviewIn,
                session: Session = Depends(get_session)) -> SRSCardOut:
    card = session.get(SRSCard, card_id)
    if card is None:
        raise HTTPException(404, "card not found")
    if body.status not in _VALID_STATUS:
        raise HTTPException(422, "invalid status")
    card.status = body.status
    session.add(card)
    session.commit()
    session.refresh(card)
    return _card_out(card)


@ops_router.post("/cards/{card_id}/grade", response_model=SRSCardOut)
def grade(card_id: int, body: CardGradeIn,
          session: Session = Depends(get_session)) -> SRSCardOut:
    card = session.get(SRSCard, card_id)
    if card is None:
        raise HTTPException(404, "card not found")
    if body.result not in _VALID_RESULT:
        raise HTTPException(422, "invalid result")
    return _card_out(grade_card(session, card, body.result))
