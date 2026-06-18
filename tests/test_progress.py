from sqlmodel import Session

from adaptive_academy.engine.progress import topic_progress
from adaptive_academy.models import Item, Phase, Topic, Track


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


def _phase(session: Session, track_id: int) -> Phase:
    p = Phase(track_id=track_id, title="P", position=0)
    session.add(p)
    session.commit()
    session.refresh(p)
    return p


def test_topic_progress_fraction_done(session):
    t, tr = _topic_with_track(session)
    p = _phase(session, tr.id)
    session.add(Item(phase_id=p.id, text="a", position=0, status="done"))
    session.add(Item(phase_id=p.id, text="b", position=1, status="done"))
    session.add(Item(phase_id=p.id, text="c", position=2, status="todo"))
    session.add(Item(phase_id=p.id, text="d", position=3, status="doing"))
    session.commit()
    assert topic_progress(session, t.id) == 0.5  # 2 of 4 done


def test_topic_progress_zero_without_items(session):
    t, tr = _topic_with_track(session)
    _phase(session, tr.id)  # phase but no items
    assert topic_progress(session, t.id) == 0.0


def test_topic_progress_zero_without_track(session):
    t = Topic(title="No track")
    session.add(t)
    session.commit()
    session.refresh(t)
    assert topic_progress(session, t.id) == 0.0
