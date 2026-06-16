# tests/test_retention_orchestrator.py
import json
from datetime import datetime, timezone

from sqlmodel import Session, select

from adaptive_academy.engine.retention import grade_card, propose_retention
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, RecallPrompt, SRSCard, Topic, Track,
)


def _concept(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax", is_load_bearing=True)
    session.add(concept)
    session.commit()
    return concept


def test_propose_retention_creates_proposed_cards_and_prompts(session: Session):
    concept = _concept(session)
    a = Assessment(concept_id=concept.id, kind="self_explanation", prompt="p", score=0.4,
                   gaps=["omitted required element: subtract the max"])
    session.add(a)
    session.commit()
    payload = json.dumps({
        "cards": [{"front": "why subtract max in softmax?", "back": "numerical stability"}],
        "prompts": ["Without looking, derive softmax and explain the max-subtraction."],
    })
    llm = ScriptedLLMClient([LLMResponse(text=payload)])
    cards, prompts = propose_retention(session, concept, a, llm=llm)
    assert len(cards) == 1 and cards[0].status == "proposed"
    assert len(prompts) == 1 and prompts[0].status == "proposed"
    assert session.exec(select(SRSCard)).one().concept_id == concept.id
    assert session.exec(select(RecallPrompt)).one().prompt.startswith("Without looking")


def test_grade_card_applies_sm2_and_advances_due(session: Session):
    concept = _concept(session)
    card = SRSCard(concept_id=concept.id, front="f", back="b", status="active",
                   due_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    session.add(card)
    session.commit()
    updated = grade_card(session, card, "good")
    assert updated.reps == 1 and updated.interval == 1 and updated.last_result == "good"
    assert updated.due_at > datetime(2020, 1, 1, tzinfo=timezone.utc)
