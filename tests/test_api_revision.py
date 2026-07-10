import json

from fastapi.testclient import TestClient
from sqlmodel import Session

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Milestone, Program, ProgramIntent, ProgramTopicLink,
)


def _seed_program(session):
    p = Program(title="PhD prep", goal_statement="research-ready")
    session.add(p)
    session.commit()
    session.add(ProgramIntent(program_id=p.id, focus_area="custom LLMs"))
    m1 = Milestone(program_id=p.id, title="Foundations", order_index=0)
    m2 = Milestone(program_id=p.id, title="Architectures", order_index=1)
    session.add(m1)
    session.add(m2)
    session.commit()
    link = ProgramTopicLink(milestone_id=m2.id, proposed_title="Attention", status="stub")
    session.add(link)
    session.commit()
    return p, m1, m2, link


def _client(session: Session, synth: dict) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps(synth))])
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient({
        "whats_new": [RawSource(title="MoE", url="https://e.com/moe", tier=1)],
    })
    return TestClient(app)


def _synth(m2_id: int) -> dict:
    return {"map_health": "missing MoE",
            "changes": [{"kind": "add_topic",
                         "payload": {"milestone_id": m2_id, "title": "MoE routing"},
                         "why": "field moved", "source_urls": ["https://e.com/moe"]}]}


def test_revise_get_accept_flow(session):
    p, m1, m2, link = _seed_program(session)
    client = _client(session, _synth(m2.id))

    r = client.post(f"/api/programs/{p.id}/revise")
    assert r.status_code == 200
    body = r.json()
    assert body["map_health"] == "missing MoE"
    assert len(body["changes"]) == 1
    change_id = body["changes"][0]["id"]

    # open revision visible; detail flags set
    assert client.get(f"/api/programs/{p.id}/revision").json()["id"] == body["id"]
    detail = client.get(f"/api/programs/{p.id}").json()
    assert detail["has_open_revision"] is True

    # second revise refused while open
    assert client.post(f"/api/programs/{p.id}/revise").status_code == 400

    r = client.post(f"/api/programs/{p.id}/changes/{change_id}/accept")
    assert r.status_code == 200
    detail = r.json()
    assert detail["has_open_revision"] is False
    titles = [link["proposed_title"] for m in detail["milestones"] for link in m["links"]]
    assert "MoE routing" in titles
    added = [link for m in detail["milestones"] for link in m["links"]
             if link["proposed_title"] == "MoE routing"]
    assert added[0]["added_by"] == "revision"

    # revision now resolved -> GET 404, change re-resolve 400
    assert client.get(f"/api/programs/{p.id}/revision").status_code == 404
    assert client.post(f"/api/programs/{p.id}/changes/{change_id}/reject").status_code == 400


def test_reject_and_cross_program_guards(session):
    p, m1, m2, link = _seed_program(session)
    client = _client(session, _synth(m2.id))
    change_id = client.post(f"/api/programs/{p.id}/revise").json()["changes"][0]["id"]

    other = Program(title="Other", goal_statement="g")
    session.add(other)
    session.commit()
    assert client.post(f"/api/programs/{other.id}/changes/{change_id}/accept").status_code == 404

    r = client.post(f"/api/programs/{p.id}/changes/{change_id}/reject")
    assert r.status_code == 200
    assert r.json()["has_open_revision"] is False


def test_archived_milestone_gate_is_400(session):
    p, m1, m2, link = _seed_program(session)
    m2.archived = True
    session.add(m2)
    session.commit()
    client = _client(session, _synth(m2.id))
    r = client.get(f"/api/programs/{p.id}/milestones/{m2.id}/gate")
    assert r.status_code == 400
    assert "archived" in r.json()["detail"]
