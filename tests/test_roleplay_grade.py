# tests/test_roleplay_grade.py  (uses the `session` fixture from conftest.py)
import json

from sqlmodel import select

from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.models import (
    Program, Milestone, Track, Topic, Concept, KnowledgeEstimate, Rubric,
    ProgramTopicLink, RoleplaySession, RoleplayTurn, Assessment,
)
from adaptive_academy.engine.roleplay import grade_roleplay


def _ended_session(s):
    p = Program(title="B2B", goal_statement="g")
    s.add(p)
    s.commit()
    s.refresh(p)
    m = Milestone(program_id=p.id, title="Discovery", success_criteria="run a discovery call")
    s.add(m)
    s.commit()
    s.refresh(m)
    t = Topic(title="Discovery")
    s.add(t)
    s.commit()
    s.refresh(t)
    tr = Track(topic_id=t.id, title="tr")
    s.add(tr)
    s.commit()
    s.refresh(tr)
    c = Concept(track_id=tr.id, name="SPIN questioning", is_load_bearing=True)
    s.add(c)
    s.commit()
    s.refresh(c)
    s.add(KnowledgeEstimate(concept_id=c.id, level="low"))
    # Pre-seed a reviewed rubric so assess_concept does not need to generate one.
    s.add(Rubric(concept_id=c.id, criteria=["asks implication questions"],
                 must_include=["implication"], weak_signs=[]))
    s.add(ProgramTopicLink(milestone_id=m.id, topic_id=t.id, status="started"))
    rp = RoleplaySession(program_id=p.id, milestone_id=m.id, status="ended",
                         persona_brief={"persona": "VP"})
    s.add(rp)
    s.commit()
    s.refresh(rp)
    s.add(RoleplayTurn(session_id=rp.id, role="user",
                       content="What happens if that stays broken? (implication)"))
    s.add(RoleplayTurn(session_id=rp.id, role="persona", content="We'd lose a customer."))
    s.commit()
    return p, m, c, rp


def test_grade_writes_one_assessment_per_concept_and_outcome(session):
    p, m, c, rp = _ended_session(session)
    # 1 grade call (GRADE, via assess_concept) + 1 outcome call (ROLEPLAY_GRADE).
    grade_json = json.dumps({"score": 0.8, "verdict": "solid", "mechanism_present": True,
                             "gaps": []})
    outcome_json = json.dumps({"result": "demo booked", "summary": "Good implication q."})
    llm = ScriptedLLMClient([LLMResponse(text=grade_json), LLMResponse(text=outcome_json)])
    out = grade_roleplay(session, rp, llm=llm)
    assert len(out) == 1
    a = out[0]
    assert a.kind == "roleplay" and a.roleplay_session_id == rp.id and a.concept_id == c.id
    session.refresh(rp)
    assert rp.status == "graded"
    assert rp.outcome["result"] == "demo booked"
    rows = session.exec(select(Assessment).where(Assessment.roleplay_session_id == rp.id)).all()
    assert len(rows) == 1
