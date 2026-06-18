"""Wayfinding momentum — derived 'wind' that models persistence (whether you keep going).

Computed on the fly from completed-learning records: no tables, no cron. Wind decays from
timestamps, so it falls correctly even if the app is never opened. Kept strictly independent of
competence — we read only the *timestamp* of each real learning action, never its score/verdict.

Source reconciliation (see plan note): the spec said "derive from the AgentEvent log", but a
reality-check against the live schema showed the five real learning actions (graded probe,
teach-back, productive-failure attempt, decay recall, artifact ship) all persist as `Assessment`
rows — three of them emit no AgentEvent at all. So wind is derived from `Assessment.created_at`,
which is the unified, complete record of completed generative work. We use only the timestamp and
the concept→topic mapping; the score/verdict is never read, preserving competence independence.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlmodel import Session, select

from adaptive_academy.models import Assessment, Concept, Item, Phase, Topic, Track

HALF_LIFE_DAYS = 3.0
CRUISING_VALUE = 2.0
FADING_DAYS = 4
BECALMED_DAYS = 10

# Assessment.kind values that count as a real, completed learning action filling the sails.
# Every Assessment is a graded generative effort, so all kinds qualify; the allowlist stays
# explicit so a future non-learning assessment kind can be excluded deliberately.
QUALIFYING_KINDS: set[str] = {
    "self_explanation",
    "calibration",
    "source_quiz",
    "recall",
    "teach",
    "productive_failure",
    "artifact_review",
}


def _naive_utc(dt: datetime) -> datetime:
    """Coerce to naive UTC so aware (in-memory ORM) and naive (SQLite-read) times compare.

    SQLite returns naive datetimes; freshly-constructed ORM objects carry tz-aware UTC.
    """
    if dt.tzinfo is not None:
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def decayed_wind(event_times: list[datetime], now: datetime) -> float:
    now = _naive_utc(now)
    total = 0.0
    for t in event_times:
        age_days = (now - _naive_utc(t)).total_seconds() / 86400.0
        if age_days < 0:
            age_days = 0.0
        total += 0.5 ** (age_days / HALF_LIFE_DAYS)
    return total


def classify(value: float, days_since: float | None) -> str:
    if days_since is None:
        return "unsailed"  # never had a learning action — distinct from a real lapse
    if days_since >= BECALMED_DAYS:
        return "becalmed"
    if days_since >= FADING_DAYS:
        return "fading"
    if value >= CRUISING_VALUE:
        return "cruising"
    return "steady"


# Attention-first: lapsed voyages demand wind; never-sailed ones sit at the bottom (parked, not
# at-risk), so the Fleet surfaces real abandonment risk above topics that simply haven't launched.
_ATTENTION_ORDER = {"becalmed": 0, "fading": 1, "steady": 2, "cruising": 3, "unsailed": 4}


@dataclass
class WindState:
    topic_id: int
    topic_title: str
    value: float
    state: str
    last_sailed: datetime | None
    days_since: float | None


def _utcnow() -> datetime:
    return datetime.utcnow()


def _qualifying_times(session: Session, topic_id: int) -> set[datetime]:
    """Timestamps of every real learning action under this topic, deduped.

    Assessments join concept→track→topic. A set collapses the identical timestamps a single
    artifact ship writes across its phase's concepts, so one ship counts as one action.
    """
    track_ids = session.exec(select(Track.id).where(Track.topic_id == topic_id)).all()
    if not track_ids:
        return set()
    concept_ids = session.exec(
        select(Concept.id).where(Concept.track_id.in_(track_ids))).all()
    if not concept_ids:
        return set()
    rows = session.exec(
        select(Assessment).where(Assessment.concept_id.in_(concept_ids))).all()
    # Round to the whole second before deduping: an artifact ship writes one row per concept in a
    # loop, so default_factory=_now gives them sub-second-apart timestamps. Without rounding the
    # set keeps them all and one ship reads as N gusts. Two *deliberate* human actions in the same
    # literal second is implausible (each grade is an LLM round-trip), so this only collapses
    # same-commit bursts.
    return {
        _naive_utc(a.created_at).replace(microsecond=0)
        for a in rows
        if a.kind in QUALIFYING_KINDS
    }


def topic_wind(session: Session, topic_id: int, *, now: datetime | None = None) -> WindState:
    now = _naive_utc(now or _utcnow())
    topic = session.get(Topic, topic_id)
    title = topic.title if topic else ""
    times = _qualifying_times(session, topic_id)
    value = decayed_wind(list(times), now)
    last = max(times) if times else None
    days_since = (now - _naive_utc(last)).total_seconds() / 86400.0 if last else None
    return WindState(
        topic_id, title, round(value, 4), classify(value, days_since), last, days_since)


def fleet(session: Session, *, now: datetime | None = None) -> list[WindState]:
    now = now or _utcnow()
    topics = session.exec(select(Topic)).all()
    states = [topic_wind(session, t.id, now=now) for t in topics]
    states.sort(key=lambda w: (_ATTENTION_ORDER.get(w.state, 9), -w.value))
    return states


@dataclass
class ComebackMove:
    kind: str
    label: str
    href: str
    minutes: int


def comeback_move(
    session: Session, topic_id: int, *, now: datetime | None = None
) -> ComebackMove | None:
    """One high-value, low-friction re-entry move when the voyage is fading/becalmed.

    The C-shaped seam: v1 reads only wind + curriculum; a future version could read/write stored
    comeback state without any caller changing. Returns None when the voyage is healthy.
    """
    ws = topic_wind(session, topic_id, now=now)
    if ws.state not in ("fading", "becalmed", "unsailed"):
        return None
    track = session.exec(select(Track).where(Track.topic_id == topic_id)).first()
    if track is not None:
        phases = session.exec(
            select(Phase).where(Phase.track_id == track.id).order_by(Phase.position)).all()
        for p in phases:
            items = session.exec(
                select(Item).where(Item.phase_id == p.id).order_by(Item.position)).all()
            for it in items:
                if it.status != "done":
                    return ComebackMove(
                        kind=it.type, label=it.text[:120],
                        href=f"/topics/{topic_id}/track", minutes=25)
    return ComebackMove(
        kind="self_explain",
        label="Do a quick self-explanation on a load-bearing concept",
        href=f"/topics/{topic_id}/assess", minutes=15)
