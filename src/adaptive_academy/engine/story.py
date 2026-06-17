"""Progress Story — a generation-first build-in-public narrative of a learner's journey.

Deterministic facts are gathered in code (so the narrative is grounded in real numbers,
not hallucinated), then a single LLM call narrates them in an honest, second-person,
build-in-public voice. Pedagogy: the generation effect + metacognitive reflection.
"""

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

from sqlmodel import Session, select

from adaptive_academy.llm.types import LLMClient
from adaptive_academy.prompts import STORY
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    Deliverable,
    Item,
    KnowledgeEstimate,
    Phase,
    Topic,
    TopicIntent,
    Track,
)

_LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2, "unknown": -1}


class StoryError(Exception):
    """Raised when a story can't be composed (e.g. unknown topic)."""


@dataclass
class StoryFacts:
    topic_title: str = ""
    goal: str = ""
    span_days: int = 0
    items_done: int = 0
    items_total: int = 0
    progress_pct: int = 0
    phases_completed: int = 0
    phases_total: int = 0
    shipped: list[str] = field(default_factory=list)
    concepts_solid: list[str] = field(default_factory=list)
    concepts_developing: list[str] = field(default_factory=list)
    concepts_shaky: list[str] = field(default_factory=list)
    load_bearing_shaky: list[str] = field(default_factory=list)
    assessments_count: int = 0
    mean_score: float | None = None
    improvements: list[str] = field(default_factory=list)
    calibration_note: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class StoryResult:
    headline: str
    narrative: list[str]
    highlights: list[str]
    facts: StoryFacts
    events: list[AgentEvent]


def _concepts_for(session: Session, topic_id: int) -> list[Concept]:
    return session.exec(select(Concept).join(Track).where(Track.topic_id == topic_id)).all()


def gather_story_facts(session: Session, topic_id: int) -> StoryFacts:
    """Collect deterministic, real facts about the learner's progress on a topic."""
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise StoryError("topic not found")

    intent = session.exec(select(TopicIntent).where(TopicIntent.topic_id == topic_id)).first()
    facts = StoryFacts(topic_title=topic.title, goal=intent.goal if intent else "")

    track = session.exec(select(Track).where(Track.topic_id == topic_id)).first()
    concepts = _concepts_for(session, topic_id)

    # Track / phase progress.
    if track is not None:
        phases = session.exec(select(Phase).where(Phase.track_id == track.id)).all()
        facts.phases_total = len(phases)
        for p in phases:
            items = session.exec(select(Item).where(Item.phase_id == p.id)).all()
            done = [i for i in items if i.status == "done"]
            facts.items_total += len(items)
            facts.items_done += len(done)
            if items and len(done) == len(items):
                facts.phases_completed += 1
            deliverable = session.exec(
                select(Deliverable).where(Deliverable.phase_id == p.id)
            ).first()
            if deliverable and deliverable.artifact_url:
                facts.shipped.append(deliverable.text)
        facts.progress_pct = (
            round(100 * facts.items_done / facts.items_total) if facts.items_total else 0
        )

    # Concepts by mastery level.
    for c in concepts:
        est = session.exec(
            select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == c.id)
        ).first()
        level = est.level if est else "unknown"
        if level == "high":
            facts.concepts_solid.append(c.name)
        elif level == "medium":
            facts.concepts_developing.append(c.name)
        elif level == "low":
            facts.concepts_shaky.append(c.name)
            if c.is_load_bearing:
                facts.load_bearing_shaky.append(c.name)

    # Assessments: count, mean, improvements, calibration trend.
    concept_ids = [c.id for c in concepts]
    assessments: list[Assessment] = []
    if concept_ids:
        assessments = session.exec(
            select(Assessment).where(Assessment.concept_id.in_(concept_ids)).order_by(Assessment.id)
        ).all()
    facts.assessments_count = len(assessments)
    if assessments:
        facts.mean_score = round(sum(a.score for a in assessments) / len(assessments), 2)
        name_by_id = {c.id: c.name for c in concepts}
        for a in assessments:
            if a.delta is not None and a.delta > 0.05:
                facts.improvements.append(
                    f"{name_by_id.get(a.concept_id, 'a concept')} improved by {a.delta:+.2f}"
                )

        # Calibration: compare predicted vs actual where both exist.
        cal = [
            (a.confidence_predicted, a.confidence_actual)
            for a in assessments
            if a.confidence_predicted is not None and a.confidence_actual is not None
        ]
        if cal:
            gap = sum(p - act for p, act in cal) / len(cal)
            if gap > 0.12:
                facts.calibration_note = "tends to be overconfident"
            elif gap < -0.12:
                facts.calibration_note = "tends to be underconfident"
            else:
                facts.calibration_note = "well-calibrated"

        # Span in days from first to last assessment.
        stamps = [a.created_at for a in assessments]
        span = max(stamps) - min(stamps)
        facts.span_days = max(0, span.days)
    else:
        # No assessments yet — span since the topic was created.
        if topic.created_at:
            now = datetime.now(timezone.utc)
            created = topic.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            facts.span_days = max(0, (now - created).days)

    return facts


def build_story_prompt(facts: StoryFacts) -> tuple[str, str]:
    f = facts
    lines = [
        f"TOPIC: {f.topic_title}",
        f"GOAL: {f.goal or '(none stated)'}",
        f"TIMESPAN: {f.span_days} days of activity",
        f"TRACK PROGRESS: {f.items_done}/{f.items_total} steps "
        f"({f.progress_pct}%), {f.phases_completed}/{f.phases_total} phases complete",
        f"SHIPPED ARTIFACTS: {', '.join(f.shipped) if f.shipped else '(none yet)'}",
        f"SOLID CONCEPTS: {', '.join(f.concepts_solid) or '(none yet)'}",
        f"DEVELOPING CONCEPTS: {', '.join(f.concepts_developing) or '(none)'}",
        f"SHAKY CONCEPTS: {', '.join(f.concepts_shaky) or '(none)'}",
        f"SHAKY LOAD-BEARING (priority): {', '.join(f.load_bearing_shaky) or '(none)'}",
        f"ASSESSMENTS: {f.assessments_count}, mean score "
        f"{f.mean_score if f.mean_score is not None else 'n/a'}",
        f"IMPROVEMENTS: {'; '.join(f.improvements) if f.improvements else '(none recorded)'}",
        f"CALIBRATION: {f.calibration_note or 'not enough data'}",
    ]
    return STORY, "\n".join(lines)


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def parse_story_json(text: str) -> tuple[str, list[str], list[str]]:
    d = json.loads(_strip_fences(text))
    headline = str(d.get("headline", "")).strip()
    narrative = [str(p).strip() for p in (d.get("narrative", []) or []) if str(p).strip()]
    highlights = [str(h).strip() for h in (d.get("highlights", []) or []) if str(h).strip()]
    return headline, narrative, highlights


def generate_story(session: Session, topic_id: int, *, llm: LLMClient) -> StoryResult:
    """Gather real facts, then narrate them in one LLM call. Persists observability events."""
    facts = gather_story_facts(session, topic_id)
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic_id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    emit("story:compose", f"{facts.assessments_count} assessments, {facts.progress_pct}% progress")
    emit("prompt", STORY.tag)
    system, user = build_story_prompt(facts)
    resp = llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[])
    headline, narrative, highlights = parse_story_json(resp.text)
    emit("story:done", headline[:60])
    session.commit()

    return StoryResult(
        headline=headline or "Your journey so far",
        narrative=narrative or ["You're just getting started — the story writes itself from here."],
        highlights=highlights,
        facts=facts,
        events=events,
    )
