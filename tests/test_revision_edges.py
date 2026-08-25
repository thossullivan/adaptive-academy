from sqlmodel import Session, col, select

from adaptive_academy.engine.revision import apply_change, reject_change
from adaptive_academy.models import (
    AgentEvent,
    Concept,
    ConceptEdge,
    MapChange,
    MapRevision,
    Milestone,
    Program,
    ProgramTopicLink,
    Topic,
    Track,
)


def _seed_change_with_edges(session: Session):
    program = Program(title="Program")
    session.add(program)
    session.flush()
    milestone = Milestone(program_id=program.id, title="Milestone")
    session.add(milestone)
    session.flush()

    pruned_topic = Topic(title="Pruned")
    retained_topic = Topic(title="Retained")
    session.add_all([pruned_topic, retained_topic])
    session.flush()
    pruned_track = Track(topic_id=pruned_topic.id, title="Pruned")
    retained_track = Track(topic_id=retained_topic.id, title="Retained")
    session.add_all([pruned_track, retained_track])
    session.flush()
    first = Concept(track_id=pruned_track.id, name="First")
    second = Concept(track_id=pruned_track.id, name="Second")
    third = Concept(track_id=retained_track.id, name="Third")
    fourth = Concept(track_id=retained_track.id, name="Fourth")
    session.add_all([first, second, third, fourth])
    session.flush()

    touching_out = ConceptEdge(
        src_concept_id=first.id,
        dst_concept_id=second.id,
        kind="prerequisite",
        origin="researcher",
    )
    touching_in = ConceptEdge(
        src_concept_id=third.id,
        dst_concept_id=first.id,
        kind="alias",
        origin="alias",
    )
    untouched = ConceptEdge(
        src_concept_id=third.id,
        dst_concept_id=fourth.id,
        kind="related",
        origin="learner",
    )
    session.add_all([touching_out, touching_in, untouched])
    link = ProgramTopicLink(
        milestone_id=milestone.id,
        topic_id=pruned_topic.id,
        proposed_title="Pruned",
        status="stub",
    )
    session.add(link)
    revision = MapRevision(program_id=program.id)
    session.add(revision)
    session.flush()
    change = MapChange(
        revision_id=revision.id,
        kind="prune_topic",
        payload={"link_id": link.id},
    )
    session.add(change)
    session.commit()
    return program, link, change, touching_out, touching_in, untouched


def test_accept_prune_topic_invalidates_touching_edges_and_emits_event(session: Session):
    program, link, change, touching_out, touching_in, untouched = (
        _seed_change_with_edges(session)
    )

    apply_change(session, program, change)

    for row in (touching_out, touching_in, untouched):
        session.refresh(row)
    session.refresh(link)
    assert touching_out.valid_until is not None
    assert touching_in.valid_until is not None
    assert untouched.valid_until is None
    assert len(session.exec(select(ConceptEdge)).all()) == 3
    event = session.exec(
        select(AgentEvent).where(
            AgentEvent.program_id == program.id,
            AgentEvent.kind == "graph:invalidate",
        )
    ).one()
    assert event.detail == f"2 edges, mapchange:{change.id}"
    assert link.status == "pruned"


def test_reject_prune_topic_leaves_edges_and_link_untouched(session: Session):
    program, link, change, *_ = _seed_change_with_edges(session)

    reject_change(session, change)

    assert session.exec(
        select(ConceptEdge).where(col(ConceptEdge.valid_until).is_(None))
    ).all() == session.exec(select(ConceptEdge)).all()
    assert session.exec(
        select(AgentEvent).where(AgentEvent.kind == "graph:invalidate")
    ).all() == []
    session.refresh(link)
    assert link.status == "stub"
