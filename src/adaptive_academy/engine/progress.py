"""Voyage distance — curriculum coverage, the orthogonal partner to momentum's 'wind'.

Distance = how far a voyage has sailed toward its North Star: the fraction of the topic's concepts
that have been genuinely assessed (waypoints reached). Kept separate from `engine/momentum.py` on
purpose: momentum (wind) and progress (distance) are two orthogonal quantities on the same voyage.
The Fleet view combines them — height = distance, liveliness = wind — but the engines never touch.

Coverage counts only real `Assessment` rows, so it is immune to the `KnowledgeEstimate` default of
'high' (a never-sailed topic must read 0%, not pinned to the star). Mastery *depth* is a separate
axis owned by the competence verdicts; distance only asks "have you reached this waypoint at all?".
"""

from sqlmodel import Session, select

from adaptive_academy.models import Assessment, Concept, Track


def topic_progress(session: Session, topic_id: int) -> float:
    """Fraction (0..1) of the topic's concepts with at least one real assessment. 0.0 if none."""
    track_ids = session.exec(select(Track.id).where(Track.topic_id == topic_id)).all()
    if not track_ids:
        return 0.0
    concept_ids = session.exec(select(Concept.id).where(Concept.track_id.in_(track_ids))).all()
    if not concept_ids:
        return 0.0
    assessed = session.exec(
        select(Assessment.concept_id).where(Assessment.concept_id.in_(concept_ids))).all()
    return round(len(set(assessed)) / len(concept_ids), 4)
