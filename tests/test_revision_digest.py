from datetime import datetime, timedelta

from adaptive_academy.engine.revision import build_learnings_digest
from adaptive_academy.models import (
    Assessment, Concept, ConceptAlias, KnowledgeEstimate, Milestone, Program,
    ProgramTopicLink, Topic, Track,
)

T0 = datetime(2026, 7, 1)


def _program_with_two_legs(session):
    p = Program(title="PhD prep", goal_statement="research-ready")
    session.add(p)
    session.commit()
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0,
                   gate_status="passed")
    m2 = Milestone(program_id=p.id, title="Architectures", order_index=1)
    m3 = Milestone(program_id=p.id, title="Old leg", order_index=2, archived=True)
    session.add(m1)
    session.add(m2)
    session.add(m3)
    topic = Topic(title="Backprop")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Backprop")
    session.add(track)
    session.commit()
    c = Concept(track_id=track.id, name="Chain rule", is_load_bearing=True)
    session.add(c)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=c.id, level="medium"))
    session.add(Assessment(concept_id=c.id, kind="teach", prompt="p", score=0.9,
                           created_at=T0))
    session.add(Assessment(concept_id=c.id, kind="recall", prompt="p", score=0.85,
                           created_at=T0 + timedelta(days=8)))
    session.add(ProgramTopicLink(milestone_id=m1.id, topic_id=topic.id, status="started"))
    session.add(ProgramTopicLink(milestone_id=m2.id, proposed_title="Attention", status="stub"))
    session.add(ConceptAlias(program_id=p.id, canonical_name="chain rule", concept_id=c.id))
    session.commit()
    return p


def test_digest_covers_legs_evidence_and_knowledge(session):
    p = _program_with_two_legs(session)
    digest = build_learnings_digest(session, p)
    assert "LEG 1: Foundations [gate: passed]" in digest
    assert "1 started" in digest
    assert "Chain rule=verified" in digest       # per-concept evidence verdict
    assert "LEG 2: Architectures [gate: open]" in digest
    assert "1 stub" in digest
    assert "chain rule=medium" in digest         # alias-group knowledge level
    assert "Old leg" not in digest               # archived legs skipped


def test_digest_is_deterministic_and_handles_empty(session):
    p = Program(title="Empty", goal_statement="g")
    session.add(p)
    session.commit()
    d1 = build_learnings_digest(session, p)
    d2 = build_learnings_digest(session, p)
    assert d1 == d2
    assert "no milestones yet" in d1
