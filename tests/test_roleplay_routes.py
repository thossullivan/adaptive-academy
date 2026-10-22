import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.prompts import grade_prompt
from adaptive_academy.models import (
    Concept, KnowledgeEstimate, Milestone, Program, ProgramTopicLink, Rubric, Track, Topic,
)


def _client(session, responses):
    # One shared ScriptedLLMClient so its queued responses consume IN SEQUENCE across the
    # three HTTP requests (start → turn → end); a fresh client per request would restart the queue.
    app = create_app()
    llm = ScriptedLLMClient(responses)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)


def _seed_materialized(s):
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
    c = Concept(track_id=tr.id, name="SPIN", is_load_bearing=True)
    s.add(c)
    s.commit()
    s.refresh(c)
    s.add(KnowledgeEstimate(concept_id=c.id, level="low"))
    s.add(Rubric(concept_id=c.id, criteria=["asks implication"], must_include=[], weak_signs=[]))
    s.add(ProgramTopicLink(milestone_id=m.id, topic_id=t.id, status="started"))
    s.commit()
    return p.id, m.id


def _seed_unmaterialized(s):
    p = Program(title="B2B", goal_statement="g")
    s.add(p)
    s.commit()
    s.refresh(p)
    m = Milestone(program_id=p.id, title="Discovery", success_criteria="c")
    s.add(m)
    s.commit()
    s.refresh(m)
    return p.id, m.id


def test_spar_requires_materialized_milestone(session):
    pid, mid = _seed_unmaterialized(session)
    client = _client(session, [])
    r = client.post(f"/api/programs/{pid}/milestones/{mid}/roleplay")
    assert r.status_code == 400


def test_full_roleplay_flow(session):
    pid, mid = _seed_materialized(session)
    brief = {"persona": "VP", "goal": "resist", "situation": "call",
             "hidden_objections": [], "win_conditions": [], "difficulty": "low"}
    grade = {"score": 0.8, "verdict": "solid", "mechanism_present": True, "gaps": [],
             "missing_required": [], "misconceptions_committed": []}
    outcome = {"result": "demo booked", "summary": "ok"}
    client = _client(session, [LLMResponse(text=json.dumps(brief)),      # director
                               LLMResponse(text="Who is this? [[END]]"),  # persona turn (ends)
                               LLMResponse(text=json.dumps(grade)),       # concept grade
                               LLMResponse(text=json.dumps(outcome))])    # outcome
    r = client.post(f"/api/programs/{pid}/milestones/{mid}/roleplay")
    assert r.status_code == 200
    sid = r.json()["session_id"]
    assert "hidden_objections" not in r.json()["brief_public"]   # brief is public-only
    r2 = client.post(f"/api/roleplay/{sid}/turns", json={"content": "hello"})
    assert r2.json()["status"] == "ended"
    r3 = client.post(f"/api/roleplay/{sid}/end")
    body = r3.json()
    assert body["status"] == "graded"
    assert body["outcome"]["result"] == "demo booked"
    assert body["scorecard"][0]["concept"] == "SPIN"
    assert body["scorecard"][0]["prompt_tag"] == grade_prompt().tag


def test_turn_route_reports_an_unrecorded_turn_legibly(session):
    pid, mid = _seed_materialized(session)
    brief = {"persona": "VP", "goal": "resist", "situation": "call",
             "hidden_objections": [], "win_conditions": [], "difficulty": "low"}
    client = _client(session, [LLMResponse(text=json.dumps(brief)),
                               LLMResponse(text="", stop_reason="refusal"),
                               LLMResponse(text="Who is this?")])
    sid = client.post(f"/api/programs/{pid}/milestones/{mid}/roleplay").json()["session_id"]

    r = client.post(f"/api/roleplay/{sid}/turns", json={"content": "declined"})
    assert r.status_code == 200
    assert r.json()["recorded"] is False
    assert r.json()["status"] == "active"
    assert "wasn't recorded" in r.json()["reply"]

    r2 = client.post(f"/api/roleplay/{sid}/turns", json={"content": "hello"})
    assert r2.json() == {"reply": "Who is this?", "status": "active", "recorded": True}
    turns = client.get(f"/api/roleplay/{sid}").json()["turns"]
    assert [(t["role"], t["content"]) for t in turns] == [
        ("user", "hello"), ("persona", "Who is this?")]
