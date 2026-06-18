"""Voyage distance — curriculum progress, the orthogonal partner to momentum's 'wind'.

Distance = how far a voyage has sailed toward its North Star (fraction of curriculum items done).
Kept separate from `engine/momentum.py` on purpose: momentum (wind) and progress (distance) are two
orthogonal quantities on the same voyage. The Fleet view combines them — height = distance, liveliness
= wind — but the engines never touch each other.
"""

from sqlmodel import Session, select

from adaptive_academy.models import Item, Phase, Track


def topic_progress(session: Session, topic_id: int) -> float:
    """Fraction (0..1) of curriculum items completed across a topic's track. 0.0 if none yet."""
    track_ids = session.exec(select(Track.id).where(Track.topic_id == topic_id)).all()
    if not track_ids:
        return 0.0
    phase_ids = session.exec(select(Phase.id).where(Phase.track_id.in_(track_ids))).all()
    if not phase_ids:
        return 0.0
    items = session.exec(select(Item).where(Item.phase_id.in_(phase_ids))).all()
    if not items:
        return 0.0
    done = sum(1 for it in items if it.status == "done")
    return round(done / len(items), 4)
