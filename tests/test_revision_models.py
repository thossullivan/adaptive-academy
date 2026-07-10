from sqlmodel import select

from adaptive_academy.models import (
    MapChange,
    MapRevision,
    Milestone,
    Program,
    ProgramTopicLink,
)


def test_map_revision_tables_roundtrip(session):
    program = Program(title="P", goal_statement="g")
    session.add(program)
    session.commit()

    rev = MapRevision(program_id=program.id, map_health="field moved to MoE")
    session.add(rev)
    session.commit()
    session.refresh(rev)
    assert rev.created_at is not None

    change = MapChange(
        revision_id=rev.id,
        kind="add_topic",
        payload={"milestone_id": 1, "title": "MoE routing"},
        why="new frontier",
        source_urls=["https://example.com/moe"],
    )
    session.add(change)
    session.commit()
    session.refresh(change)
    assert change.status == "proposed"
    assert change.payload == {"milestone_id": 1, "title": "MoE routing"}
    assert change.source_urls == ["https://example.com/moe"]


def test_new_columns_default(session):
    program = Program(title="P", goal_statement="g")
    session.add(program)
    session.commit()
    m = Milestone(program_id=program.id, title="M", order_index=0)
    link = ProgramTopicLink(milestone_id=1, proposed_title="T")
    session.add(m)
    session.add(link)
    session.commit()
    session.refresh(m)
    session.refresh(link)
    assert m.archived is False
    assert link.added_by == "research"
    assert session.exec(select(Milestone).where(Milestone.archived == False)).all()  # noqa: E712
