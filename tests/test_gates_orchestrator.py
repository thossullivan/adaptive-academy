from datetime import datetime, timedelta

from adaptive_academy.engine.gates import milestone_gate
from adaptive_academy.models import (
    AgentEvent, Assessment, Concept, Milestone, Program, ProgramTopicLink, Topic, Track,
)
from sqlmodel import select as _select

T0 = datetime(2026, 7, 1, 12, 0, 0)


def _seed_milestone(session, *, started: bool = True):
    program = Program(title="P", goal_statement="g")
    session.add(program)
    session.commit()
    m = Milestone(program_id=program.id, title="M", order_index=0)
    session.add(m)
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="T")
    session.add(track)
    session.commit()
    lb = Concept(track_id=track.id, name="Attention", is_load_bearing=True)
    minor = Concept(track_id=track.id, name="Trivia", is_load_bearing=False)
    session.add(lb)
    session.add(minor)
    session.commit()
    link = ProgramTopicLink(milestone_id=m.id, topic_id=topic.id,
                            status="started" if started else "stub")
    session.add(link)
    session.commit()
    return m, lb


def test_no_started_topics_is_open_with_no_evidence(session):
    m, _ = _seed_milestone(session, started=False)
    report = milestone_gate(session, m)
    assert report.verdict == "open"
    assert "no evidence yet" in report.reason
    assert report.concepts == []


def test_verified_evidence_passes_and_persists(session):
    m, lb = _seed_milestone(session)
    session.add(Assessment(concept_id=lb.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=lb.id, kind="recall", prompt="p", score=0.85,
                           created_at=T0 + timedelta(days=8)))
    session.commit()
    report = milestone_gate(session, m)
    assert report.verdict == "passed"
    session.refresh(m)
    assert m.gate_status == "passed"
    # non-load-bearing concepts are not consulted
    assert [e.name for e in report.concepts] == ["Attention"]


def test_passed_downgrades_when_evidence_no_longer_holds(session):
    m, lb = _seed_milestone(session)
    m.gate_status = "passed"
    session.add(m)
    session.add(Assessment(concept_id=lb.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=lb.id, kind="recall", prompt="p", score=0.2,
                           created_at=T0 + timedelta(days=8)))  # decayed
    session.commit()
    report = milestone_gate(session, m)
    assert report.verdict == "open"
    assert report.concepts[0].verdict == "stale"


def test_override_is_sticky_until_evidence_passes(session):
    m, lb = _seed_milestone(session)
    m.gate_status = "overridden"
    session.add(m)
    session.commit()
    assert milestone_gate(session, m).verdict == "overridden"
    # now evidence arrives → passed supersedes the override
    session.add(Assessment(concept_id=lb.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=lb.id, kind="recall", prompt="p", score=0.85,
                           created_at=T0 + timedelta(days=8)))
    session.commit()
    assert milestone_gate(session, m).verdict == "passed"


def test_gate_pass_transition_emits_event_once(session):
    m, lb = _seed_milestone(session)
    session.add(Assessment(concept_id=lb.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=lb.id, kind="recall", prompt="p", score=0.85,
                           created_at=T0 + timedelta(days=8)))
    session.commit()
    milestone_gate(session, m)  # open -> passed: emits
    milestone_gate(session, m)  # stays passed: must NOT emit again
    events = session.exec(_select(AgentEvent).where(
        AgentEvent.kind == "program:gate_passed")).all()
    assert len(events) == 1
    assert events[0].detail == f"milestone {m.id}"
    assert events[0].program_id is not None
