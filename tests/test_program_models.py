from adaptive_academy.models import (
    AgentEvent,
    Concept,
    ConceptAlias,
    Milestone,
    Program,
    ProgramIntent,
    ProgramTopicLink,
    Topic,
    Track,
)


def test_program_tables_roundtrip(session):
    program = Program(title="PhD-level CS: custom LLMs", goal_statement="research-ready depth")
    session.add(program)
    session.commit()
    session.refresh(program)
    assert program.status == "active"
    assert program.created_at is not None

    session.add(ProgramIntent(program_id=program.id, target_depth="phd",
                              weekly_time_budget="10h", horizon="2 years",
                              focus_area="custom LLM models"))
    m1 = Milestone(program_id=program.id, title="Math foundations",
                   success_criteria="derive backprop cold", order_index=0)
    session.add(m1)
    session.commit()
    session.refresh(m1)
    assert m1.gate_status == "open"
    assert m1.depends_on == []

    m2 = Milestone(program_id=program.id, title="Architectures", order_index=1,
                   depends_on=[m1.id])
    session.add(m2)
    session.commit()
    session.refresh(m2)
    assert m2.depends_on == [m1.id]

    link = ProgramTopicLink(milestone_id=m1.id, proposed_title="Linear algebra for DL",
                            why="prereq", sources=["https://example.com/syllabus"])
    session.add(link)
    session.commit()
    session.refresh(link)
    assert link.status == "proposed"
    assert link.topic_id is None  # proposed candidates have no Topic yet


def test_concept_alias_and_program_event(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="T")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="Attention")
    session.add(concept)
    program = Program(title="P", goal_statement="g")
    session.add(program)
    session.commit()

    session.add(ConceptAlias(program_id=program.id, canonical_name="attention",
                             concept_id=concept.id))
    session.add(AgentEvent(program_id=program.id, kind="program_research:plan", detail="5 briefs"))
    session.commit()

    ev = session.query(AgentEvent).filter(AgentEvent.program_id == program.id).one()
    assert ev.kind == "program_research:plan"
