"""Decay Check — delayed, unassisted retrieval (§8.2/§8.6/§6 of the evidence base).

The corpus is emphatic: optimize for *unassisted, delayed* performance, not in-session
success. After a concept is engaged with, we schedule a tutor-free recall probe for a few
days out; grading it re-runs an anchored `recall` assessment and surfaces the **decay** vs
the learner's prior understanding, then reschedules (held → further out, decayed → sooner).

Reuses the existing `RecallPrompt` (due_at/status) and `Assessment.kind="recall"`.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlmodel import Session, select

from adaptive_academy.engine.assess import assess_concept
from adaptive_academy.engine.memory import index_question, topic_id_for_concept
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import Assessment, Concept, RecallPrompt, Track
from adaptive_academy.prompts import DECAY_RECALL

_HELD_DAYS = 7
_DECAYED_DAYS = 2
_HELD_RATIO = 0.85  # recall must retain >=85% of prior score to count as "held"


def _naive_utc(dt: datetime) -> datetime:
    """SQLite round-trips datetimes tz-stripped; compare everything tz-naive."""
    return dt.replace(tzinfo=None) if dt.tzinfo is not None else dt


def _now_naive() -> datetime:
    return _naive_utc(datetime.now(timezone.utc))


@dataclass
class DecayResult:
    assessment: Assessment
    prompt: RecallPrompt
    baseline_score: float | None
    recall_score: float
    decay_delta: float | None  # recall_score - baseline_score (negative = forgot)
    held: bool


def schedule_decay_check(
    session: Session,
    concept_id: int,
    *,
    days: int = 3,
    retriever: Retriever | None = None,
) -> RecallPrompt:
    """Schedule (or push out) a delayed recall probe for a concept. Idempotent: one active
    prompt per concept; fresh engagement re-arms its due date."""
    due = _now_naive() + timedelta(days=days)
    existing = session.exec(
        select(RecallPrompt).where(
            RecallPrompt.concept_id == concept_id, RecallPrompt.status == "active"
        )
    ).first()
    concept = session.get(Concept, concept_id)
    topic_id = topic_id_for_concept(session, concept_id) if concept is not None else None
    if existing is not None:
        existing.due_at = due
        session.add(existing)
        index_question(
            session,
            text=existing.prompt,
            source_ref=f"recallprompt:{existing.id}",
            topic_id=topic_id,
            concept_id=concept_id,
            retriever=retriever,
        )
        session.commit()
        session.refresh(existing)
        return existing
    prompt = RecallPrompt(
        concept_id=concept_id,
        prompt=DECAY_RECALL.format(concept=concept.name if concept else "this concept"),
        status="active",
        due_at=due,
    )
    session.add(prompt)
    session.flush()
    index_question(
        session,
        text=prompt.prompt,
        source_ref=f"recallprompt:{prompt.id}",
        topic_id=topic_id,
        concept_id=concept_id,
        retriever=retriever,
    )
    session.commit()
    session.refresh(prompt)
    return prompt


def due_decay_checks(session: Session, topic_id: int) -> list[RecallPrompt]:
    """Active recall probes for a topic whose due date has arrived."""
    concept_ids = [
        c.id for c in session.exec(select(Concept).join(Track).where(Track.topic_id == topic_id)).all()
    ]
    if not concept_ids:
        return []
    cutoff = _now_naive()
    prompts = session.exec(
        select(RecallPrompt).where(
            RecallPrompt.concept_id.in_(concept_ids), RecallPrompt.status == "active"
        )
    ).all()
    return [p for p in prompts if _naive_utc(p.due_at) <= cutoff]


def _baseline_score(session: Session, concept_id: int) -> float | None:
    """The concept's most recent assessment score *before* this recall."""
    a = session.exec(
        select(Assessment).where(Assessment.concept_id == concept_id)
        .order_by(Assessment.id.desc())
    ).first()
    return a.score if a else None


def grade_decay_check(
    session: Session, prompt_id: int, response: str, *, llm: LLMClient
) -> DecayResult:
    """Grade a delayed recall unassisted, compute decay vs prior understanding, reschedule."""
    prompt = session.get(RecallPrompt, prompt_id)
    if prompt is None:
        raise ValueError("recall prompt not found")
    concept = session.get(Concept, prompt.concept_id)
    if concept is None:
        raise ValueError("concept not found")

    baseline = _baseline_score(session, concept.id)
    result = assess_concept(session, concept, "recall", response, llm=llm)
    recall_score = result.assessment.score

    decay_delta = None if baseline is None else round(recall_score - baseline, 4)
    held = baseline is None or recall_score >= baseline * _HELD_RATIO

    prompt.last_result = "held" if held else "decayed"
    prompt.due_at = _now_naive() + timedelta(days=_HELD_DAYS if held else _DECAYED_DAYS)
    session.add(prompt)
    session.commit()
    session.refresh(prompt)

    return DecayResult(
        assessment=result.assessment,
        prompt=prompt,
        baseline_score=baseline,
        recall_score=recall_score,
        decay_delta=decay_delta,
        held=held,
    )
