from datetime import datetime

import pytest
from sqlmodel import select

from adaptive_academy.engine.revision import (
    apply_change,
    reject_change,
    revision_suggested,
)
from adaptive_academy.models import (
    AgentEvent, MapChange, MapRevision, Milestone, Program, ProgramTopicLink,
)


def _program(session):
    p = Program(title="P", goal_statement="g")
    session.add(p)
    session.commit()
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0)
    m2 = Milestone(program_id=p.id, title="Architectures", order_index=1)
    session.add(m1)
    session.add(m2)
    session.commit()
    link = ProgramTopicLink(milestone_id=m2.id, proposed_title="Attention", status="stub")
    session.add(link)
    rev = MapRevision(program_id=p.id)
    session.add(rev)
    session.commit()
    return p, m1, m2, link, rev


def _change(session, rev, kind, payload):
    c = MapChange(revision_id=rev.id, kind=kind, payload=payload)
    session.add(c)
    session.commit()
    session.refresh(c)
    return c


def test_apply_add_topic_creates_revision_stub(session):
    p, m1, m2, link, rev = _program(session)
    c = _change(session, rev, "add_topic", {"milestone_id": m2.id, "title": "MoE routing"})
    apply_change(session, p, c)
    assert c.status == "accepted"
    links = session.exec(select(ProgramTopicLink).where(
        ProgramTopicLink.milestone_id == m2.id)).all()
    new = [x for x in links if x.proposed_title == "MoE routing"]
    assert len(new) == 1
    assert new[0].status == "stub" and new[0].added_by == "revision"


def test_apply_add_milestone_slots_and_shifts(session):
    p, m1, m2, link, rev = _program(session)
    c = _change(session, rev, "add_milestone",
                {"after_milestone_id": m1.id, "title": "Math refresh",
                 "success_criteria": "derive it cold",
                 "topics": [{"title": "Jacobians", "why": "gap"}]})
    apply_change(session, p, c)
    ordered = session.exec(select(Milestone).where(Milestone.program_id == p.id)
                           .order_by(Milestone.order_index)).all()
    assert [m.title for m in ordered] == ["Foundations", "Math refresh", "Architectures"]
    assert [m.order_index for m in ordered] == [0, 1, 2]
    new_links = session.exec(select(ProgramTopicLink).where(
        ProgramTopicLink.milestone_id == ordered[1].id)).all()
    assert [(x.proposed_title, x.status, x.added_by) for x in new_links] == [
        ("Jacobians", "stub", "revision")]


def test_apply_prunes_and_revise(session):
    p, m1, m2, link, rev = _program(session)
    apply_change(session, p, _change(session, rev, "prune_topic", {"link_id": link.id}))
    session.refresh(link)
    assert link.status == "pruned"
    apply_change(session, p, _change(session, rev, "revise_milestone",
                                     {"milestone_id": m2.id, "success_criteria": "new bar"}))
    session.refresh(m2)
    assert m2.success_criteria == "new bar"
    apply_change(session, p, _change(session, rev, "prune_milestone", {"milestone_id": m2.id}))
    session.refresh(m2)
    assert m2.archived is True


def test_apply_revalidates_against_current_state(session):
    p, m1, m2, link, rev = _program(session)
    c = _change(session, rev, "prune_topic", {"link_id": link.id})
    link.status = "started"  # map changed between pass and accept
    session.add(link)
    session.commit()
    with pytest.raises(ValueError, match="started"):
        apply_change(session, p, c)
    session.refresh(c)
    assert c.status == "proposed"  # untouched on refusal


def test_reject_and_double_resolve_guards(session):
    p, m1, m2, link, rev = _program(session)
    c = _change(session, rev, "prune_topic", {"link_id": link.id})
    reject_change(session, c)
    assert c.status == "rejected"
    with pytest.raises(ValueError):
        apply_change(session, p, c)  # already resolved
    with pytest.raises(ValueError):
        reject_change(session, c)


def test_revision_suggested_truth_table(session):
    p = Program(title="P2", goal_statement="g")
    session.add(p)
    session.commit()
    # no events, no revisions -> False
    assert revision_suggested(session, p) is False
    # gate passed, no revision yet -> True
    session.add(AgentEvent(program_id=p.id, kind="program:gate_passed", detail="x"))
    session.commit()
    assert revision_suggested(session, p) is True
    # revision after the event -> False
    session.add(MapRevision(program_id=p.id))
    session.commit()
    assert revision_suggested(session, p) is False
    # a later gate pass -> True again
    session.add(AgentEvent(program_id=p.id, kind="program:gate_passed", detail="y"))
    session.commit()
    assert revision_suggested(session, p) is True


def test_revision_suggested_tie_fails_open(session):
    """Identical created_at on the latest revision and gate-pass event must nudge:
    the nudge is advisory, so a tie fails open rather than hiding it."""
    p = Program(title="P3", goal_statement="g")
    session.add(p)
    session.commit()
    tie = datetime(2026, 7, 10, 12, 0, 0)
    session.add(MapRevision(program_id=p.id, created_at=tie))
    session.add(AgentEvent(program_id=p.id, kind="program:gate_passed", detail="x",
                           created_at=tie))
    session.commit()
    assert revision_suggested(session, p) is True


def test_apply_add_milestone_refuses_archived_anchor(session):
    """The after_milestone_id anchor got archived between the pass and the accept:
    apply_change must refuse (ValueError) and leave the change proposed."""
    p, m1, m2, link, rev = _program(session)
    c = _change(session, rev, "add_milestone",
                {"after_milestone_id": m1.id, "title": "Math refresh"})
    m1.archived = True
    session.add(m1)
    session.commit()
    with pytest.raises(ValueError, match="after_milestone_id"):
        apply_change(session, p, c)
    session.refresh(c)
    assert c.status == "proposed"


def test_untouchable_started_link_half(session):
    """Prove the STARTED-LINK half of the untouchable rule in isolation.

    A milestone with gate_status="open" but a link with status="started" must refuse
    revise_milestone and prune_milestone via apply_change (ValueError). This branch
    is orthogonal to a passed gate.
    """
    p, m1, m2, link, rev = _program(session)
    # Set m2's link to started, but leave gate_status="open"
    m2.gate_status = "open"
    session.add(m2)
    link.status = "started"
    session.add(link)
    session.commit()

    # Try to revise m2: should fail with "started"
    c_revise = _change(session, rev, "revise_milestone",
                       {"milestone_id": m2.id, "success_criteria": "new"})
    with pytest.raises(ValueError, match="started"):
        apply_change(session, p, c_revise)
    session.refresh(c_revise)
    assert c_revise.status == "proposed"  # unchanged

    # Try to prune m2: should fail with "started"
    c_prune = _change(session, rev, "prune_milestone", {"milestone_id": m2.id})
    with pytest.raises(ValueError, match="started"):
        apply_change(session, p, c_prune)
    session.refresh(c_prune)
    assert c_prune.status == "proposed"  # unchanged
