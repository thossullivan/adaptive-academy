from sqlmodel import select

from adaptive_academy.engine.aliases import apply_program_aliases, normalize_name
from adaptive_academy.models import (
    AgentEvent, Assessment, Concept, ConceptAlias, ConceptEdge, KnowledgeEstimate, Milestone,
    Program, ProgramTopicLink, Topic, Track,
)


def test_normalize_name():
    assert normalize_name("  Self-Attention ") == "self-attention"
    assert normalize_name("BACKPROP") == "backprop"


def _seed_topic(session, program, milestone, names_levels, *, assessed=None,
                status="started"):
    """Create topic+track+concepts(+estimates) and a program link (default started)."""
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
                                 status=status))
    session.commit()
    return topic, concepts


def _assess_and_set_level(session, concept_id, score, level):
    """Simulate the learner working a concept: log an assessment, update its estimate."""
    session.add(Assessment(concept_id=concept_id, kind="self_explanation",
                           prompt="p", score=score))
    est = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept_id)
    ).one()
    est.level = level
    session.add(est)
    session.commit()


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
    assert {(e.src_concept_id, e.dst_concept_id) for e in session.exec(select(ConceptEdge)).all()} == {
        (first[0].id, second[0].id), (second[0].id, first[0].id)}
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


def test_seeds_from_most_recently_assessed_member_not_newest(session):
    """With two group members at different levels, the seed must come from the most
    recently ASSESSED member (older concept A), not the newest member (B)."""
    p, m = _program(session)
    topic_a, (concept_a,) = _seed_topic(session, p, m, [("Attention", "low")])
    apply_program_aliases(session, topic_a.id)
    topic_b, (concept_b,) = _seed_topic(session, p, m, [("attention", "high")])
    apply_program_aliases(session, topic_b.id)  # B joins the group (seeded from A)

    # Learner then works both: B assessed first, A assessed MOST RECENTLY.
    _assess_and_set_level(session, concept_b.id, 0.9, "high")
    _assess_and_set_level(session, concept_a.id, 0.6, "medium")

    # Topic C re-mentions the concept at the cold default "high".
    topic_c, (concept_c,) = _seed_topic(session, p, m, [("ATTENTION", "high")])
    r = apply_program_aliases(session, topic_c.id)
    # "medium" from A (most recently assessed) — a newest-member (max id) bug would
    # pick B ("high", equal to C's default, so nothing reported seeded).
    assert r.seeded == [(concept_c.id, "medium")]
    est = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept_c.id)
    ).one()
    assert est.level == "medium"

    # A successful apply logs an AgentEvent against the topic.
    ev = session.exec(
        select(AgentEvent).where(AgentEvent.topic_id == topic_c.id,
                                 AgentEvent.kind == "program:alias")
    ).first()
    assert ev is not None


def test_stub_link_is_noop(session):
    p, m = _program(session)
    topic, _ = _seed_topic(session, p, m, [("Attention", "low")], status="stub")
    result = apply_program_aliases(session, topic.id)
    assert result.registered == 0 and result.seeded == []
    assert session.exec(select(ConceptAlias)).all() == []


def test_seed_ignores_non_grading_rows_on_an_ungraded_member(session):
    """Only a real grade carries over: an artifact review (or teach / productive failure) on
    a never-graded member leaves its curriculum placeholder "high" in place, so it must not
    out-rank the one member with a graded assessment."""
    p, m = _program(session)
    topic_b, (graded,) = _seed_topic(session, p, m, [("Attention", "low")])
    apply_program_aliases(session, topic_b.id)
    _assess_and_set_level(session, graded.id, 0.2, "low")
    topic_a, (placeholder,) = _seed_topic(session, p, m, [("attention", "high")])
    apply_program_aliases(session, topic_a.id)
    est_a = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == placeholder.id)).one()
    est_a.level = "high"  # the curriculum placeholder, never graded
    session.add(est_a)
    for kind in ("artifact_review", "teach", "productive_failure"):
        session.add(Assessment(concept_id=placeholder.id, kind=kind, prompt="p", score=0.9))
    session.commit()

    topic_c, (concept_c,) = _seed_topic(session, p, m, [("ATTENTION", "high")])
    r = apply_program_aliases(session, topic_c.id)
    assert r.seeded == [(concept_c.id, "low")]


def test_no_graded_member_seeds_nothing(session):
    """With nothing graded in the group, every member's estimate is only a prior: keep the
    new concept's own default instead of copying another placeholder."""
    p, m = _program(session)
    topic_a, (a,) = _seed_topic(session, p, m, [("Attention", "low")])
    apply_program_aliases(session, topic_a.id)
    session.add(Assessment(concept_id=a.id, kind="artifact_review", prompt="p", score=0.9))
    session.commit()
    topic_b, (b,) = _seed_topic(session, p, m, [("attention", "high")])
    r = apply_program_aliases(session, topic_b.id)
    assert r.seeded == []
    est = session.exec(select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == b.id)).one()
    assert est.level == "high"
