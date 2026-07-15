# Uses the `session` fixture from tests/conftest.py (in-memory SQLite, PRAGMA foreign_keys=ON).
# FKs are enforced, so every referenced row must exist before it is referenced.
from sqlmodel import select

from adaptive_academy.models import (
    Program, Milestone, Topic, Track, Concept,
    RoleplaySession, RoleplayTurn, Assessment, AgentEvent,
)


def _session_row(s):
    p = Program(title="B2B Sales", goal_statement="g"); s.add(p); s.commit(); s.refresh(p)
    m = Milestone(program_id=p.id, title="Discovery", success_criteria="c")
    s.add(m); s.commit(); s.refresh(m)
    rp = RoleplaySession(
        program_id=p.id, milestone_id=m.id, status="active",
        persona_brief={"persona": "VP Eng", "goal": "resist", "situation": "cold call",
                       "hidden_objections": ["price"], "win_conditions": ["book a demo"],
                       "difficulty": "high"})
    s.add(rp); s.commit(); s.refresh(rp)
    return rp


def test_roleplay_session_and_turns_roundtrip(session):
    rp = _session_row(session)
    session.add(RoleplayTurn(session_id=rp.id, role="user", content="hi"))
    session.add(RoleplayTurn(session_id=rp.id, role="persona", content="who are you?"))
    session.commit()
    turns = session.exec(select(RoleplayTurn).where(RoleplayTurn.session_id == rp.id)
                         .order_by(RoleplayTurn.id)).all()
    assert [t.role for t in turns] == ["user", "persona"]
    assert rp.persona_brief["hidden_objections"] == ["price"]
    assert rp.outcome is None


def test_assessment_and_event_carry_roleplay_session_id(session):
    rp = _session_row(session)
    t = Topic(title="T"); session.add(t); session.commit(); session.refresh(t)
    tr = Track(topic_id=t.id, title="tr"); session.add(tr); session.commit(); session.refresh(tr)
    c = Concept(track_id=tr.id, name="SPIN"); session.add(c); session.commit(); session.refresh(c)
    a = Assessment(concept_id=c.id, kind="roleplay", prompt="p", roleplay_session_id=rp.id)
    e = AgentEvent(kind="roleplay:brief", roleplay_session_id=rp.id)
    session.add(a); session.add(e); session.commit(); session.refresh(a); session.refresh(e)
    assert a.roleplay_session_id == rp.id
    assert e.roleplay_session_id == rp.id
