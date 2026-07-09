from sqlmodel import select

from adaptive_academy.engine.aliases import apply_program_aliases, normalize_name
from adaptive_academy.models import (
    Assessment, Concept, ConceptAlias, KnowledgeEstimate, Milestone, Program,
    ProgramTopicLink, Topic, Track,
)


def test_normalize_name():
    assert normalize_name("  Self-Attention ") == "self-attention"
    assert normalize_name("BACKPROP") == "backprop"


def _seed_topic(session, program, milestone, names_levels, *, assessed=None):
    """Create topic+track+concepts(+estimates) and a started program link."""
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="T")
    session.add(track)
    session.commit()
    concepts = []
    for name, level in names_levels:
        c = Concept(track_id=track.id, name=name, is_load_bearing=True)
        session.add(c)
        session.commit()
        session.refresh(c)
        session.add(KnowledgeEstimate(concept_id=c.id, level=level))
        concepts.append(c)
    for cid, score in (assessed or []):
        session.add(Assessment(concept_id=concepts[cid].id, kind="self_explanation",
                               prompt="p", score=score))
    session.add(ProgramTopicLink(milestone_id=milestone.id, topic_id=topic.id,
                                 status="started"))
    session.commit()
    return topic, concepts


def _program(session):
    p = Program(title="P", goal_statement="g")
    session.add(p)
    session.commit()
    m = Milestone(program_id=p.id, title="M", order_index=0)
    session.add(m)
    session.commit()
    return p, m


def test_topic_outside_program_is_noop(session):
    topic = Topic(title="standalone")
    session.add(topic)
    session.commit()
    result = apply_program_aliases(session, topic.id)
    assert result.registered == 0 and result.seeded == []


def test_first_topic_registers_groups_second_topic_seeds(session):
    p, m = _program(session)
    topic1, first = _seed_topic(session, p, m,
                                [("Attention", "low"), ("Tokenization", "medium")],
                                assessed=[(0, 0.4)])
    r1 = apply_program_aliases(session, topic1.id)
    assert r1.registered == 2 and r1.seeded == []

    # second topic re-mentions "attention" (case-insensitive) with the cold default "high"
    topic2, second = _seed_topic(session, p, m, [("attention", "high"), ("RLHF", "high")])
    r2 = apply_program_aliases(session, topic2.id)
    assert r2.registered == 2  # both concepts join alias groups (one existing, one new)
    assert r2.seeded == [(second[0].id, "low")]  # seeded from most-recently-assessed member
    est = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == second[0].id)
    ).first()
    assert est.level == "low"


def test_apply_is_idempotent(session):
    p, m = _program(session)
    topic, _ = _seed_topic(session, p, m, [("Attention", "low")])
    apply_program_aliases(session, topic.id)
    r2 = apply_program_aliases(session, topic.id)
    assert r2.registered == 0  # already-aliased concepts are skipped
    assert len(session.exec(select(ConceptAlias)).all()) == 1
