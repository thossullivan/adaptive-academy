from sqlmodel import Session

from adaptive_academy.engine.progress import topic_progress
from adaptive_academy.models import Assessment, Concept, KnowledgeEstimate, Topic, Track


def _topic_with_track(session: Session) -> tuple[Topic, Track]:
    t = Topic(title="T")
    session.add(t)
    session.commit()
    session.refresh(t)
    tr = Track(topic_id=t.id, title="tr")
    session.add(tr)
    session.commit()
    session.refresh(tr)
    return t, tr


def _concept(session: Session, track_id: int, name: str) -> Concept:
    c = Concept(track_id=track_id, name=name)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def test_topic_progress_is_assessed_concept_coverage(session):
    t, tr = _topic_with_track(session)
    cs = [_concept(session, tr.id, n) for n in "abcd"]  # 4 concepts
    session.add(Assessment(concept_id=cs[0].id, kind="self_explanation", prompt=""))  # 1 assessed
    session.commit()
    assert topic_progress(session, t.id) == 0.25  # 1 of 4 concepts reached


def test_topic_progress_ignores_default_high_estimate(session):
    # A KnowledgeEstimate defaults level='high'; a concept with an estimate but NO real assessment
    # must contribute ZERO distance — otherwise never-sailed topics would pin to the North Star.
    t, tr = _topic_with_track(session)
    c = _concept(session, tr.id, "a")
    session.add(KnowledgeEstimate(concept_id=c.id))  # default level='high', but no assessment
    session.commit()
    assert topic_progress(session, t.id) == 0.0


def test_topic_progress_zero_without_concepts(session):
    t, _ = _topic_with_track(session)  # track but no concepts
    assert topic_progress(session, t.id) == 0.0


def test_topic_progress_zero_without_track(session):
    t = Topic(title="No track")
    session.add(t)
    session.commit()
    session.refresh(t)
    assert topic_progress(session, t.id) == 0.0
