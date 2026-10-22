import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.prompts import GRADE
from adaptive_academy.models import (
    Concept, KnowledgeEstimate, Milestone, Program, ProgramTopicLink, Rubric, Topic, Track,
)


def _client(session, responses):
    app = create_app()
    llm = ScriptedLLMClient(responses)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: llm
    return TestClient(app)


def _seed_materialized(s):
    p = Program(title="PhD", goal_statement="g")
    s.add(p)
    s.commit()
    s.refresh(p)
    m = Milestone(program_id=p.id, title="Transformers", success_criteria="dissect")
    s.add(m)
    s.commit()
    s.refresh(m)
    t = Topic(title="Transformers")
    s.add(t)
    s.commit()
    s.refresh(t)
    tr = Track(topic_id=t.id, title="tr")
    s.add(tr)
    s.commit()
    s.refresh(tr)
    c = Concept(track_id=tr.id, name="Self-attention", is_load_bearing=True)
    s.add(c)
    s.commit()
    s.refresh(c)
    s.add(KnowledgeEstimate(concept_id=c.id, level="low"))
    s.add(Rubric(concept_id=c.id, criteria=["QKV"], must_include=[], weak_signs=[]))
    s.add(ProgramTopicLink(milestone_id=m.id, topic_id=t.id, status="started"))
    s.commit()
    return p.id, m.id, c.id


def _seed_unmaterialized(s):
    p = Program(title="PhD", goal_statement="g")
    s.add(p)
    s.commit()
    s.refresh(p)
    m = Milestone(program_id=p.id, title="Transformers", success_criteria="c")
    s.add(m)
    s.commit()
    s.refresh(m)
    return p.id, m.id


def test_start_requires_materialized_milestone(session):
    pid, mid = _seed_unmaterialized(session)
    client = _client(session, [])
    r = client.post(f"/api/programs/{pid}/milestones/{mid}/paper-probe",
                    json={"pasted_text": "some paper"})
    assert r.status_code == 400


def test_start_requires_url_or_paste(session):
    pid, mid, _ = _seed_materialized(session)
    client = _client(session, [])
    r = client.post(f"/api/programs/{pid}/milestones/{mid}/paper-probe", json={})
    assert r.status_code == 400


def test_full_flow_paste_answer_submit(session):
    pid, mid, cid = _seed_materialized(session)
    director_json = json.dumps({"questions": [
        {"axis": "method", "prompt": "How does attention work?", "concept_ids": [cid]}]})
    grade_json = json.dumps({"score": 0.8, "verdict": "solid", "mechanism_present": True,
                             "gaps": []})
    outcome_json = json.dumps({"result": "sharp", "summary": "s"})
    client = _client(session, [LLMResponse(text=director_json), LLMResponse(text=grade_json),
                               LLMResponse(text=outcome_json)])

    r = client.post(f"/api/programs/{pid}/milestones/{mid}/paper-probe",
                    json={"pasted_text": "We propose the Transformer.", "title": "AIAYN"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "answering"
    assert body["paper"]["title"] == "AIAYN" and body["paper"]["source"] == "paste"
    assert len(body["questions"]) == 1 and body["questions"][0]["axis"] == "method"
    # the hidden concept mapping must NOT leak in the public question row
    assert "concept_ids" not in body["questions"][0]
    probe_id = body["probe_id"]

    r = client.post(f"/api/paper-probe/{probe_id}/answers",
                    json={"question_index": 0, "content": "It computes QKV."})
    assert r.status_code == 200 and r.json()["status"] == "answering"

    r = client.post(f"/api/paper-probe/{probe_id}/submit")
    assert r.status_code == 200
    graded = r.json()
    assert graded["status"] == "graded"
    assert graded["outcome"]["result"] == "sharp"
    assert graded["scorecard"][0]["concept"] == "Self-attention"
    assert graded["scorecard"][0]["score"] == 0.8
    assert graded["scorecard"][0]["prompt_tag"] == GRADE.tag


def test_answer_rejected_when_not_answering(session):
    pid, mid, cid = _seed_materialized(session)
    director_json = json.dumps({"questions": [
        {"axis": "method", "prompt": "q", "concept_ids": [cid]}]})
    grade_json = json.dumps({"score": 0.8, "verdict": "ok", "mechanism_present": True, "gaps": []})
    outcome_json = json.dumps({"result": "r", "summary": "s"})
    client = _client(session, [LLMResponse(text=director_json), LLMResponse(text=grade_json),
                               LLMResponse(text=outcome_json)])
    probe_id = client.post(f"/api/programs/{pid}/milestones/{mid}/paper-probe",
                           json={"pasted_text": "p"}).json()["probe_id"]
    client.post(f"/api/paper-probe/{probe_id}/answers", json={"question_index": 0, "content": "a"})
    client.post(f"/api/paper-probe/{probe_id}/submit")
    r = client.post(f"/api/paper-probe/{probe_id}/answers",
                    json={"question_index": 0, "content": "late"})
    assert r.status_code == 400


def test_list_and_get(session):
    pid, mid, cid = _seed_materialized(session)
    director_json = json.dumps({"questions": [
        {"axis": "method", "prompt": "q", "concept_ids": [cid]}]})
    client = _client(session, [LLMResponse(text=director_json)])
    probe_id = client.post(f"/api/programs/{pid}/milestones/{mid}/paper-probe",
                           json={"pasted_text": "p", "title": "AIAYN"}).json()["probe_id"]
    r = client.get(f"/api/paper-probe/{probe_id}")
    assert r.status_code == 200 and r.json()["paper"]["title"] == "AIAYN"
    r = client.get(f"/api/programs/{pid}/milestones/{mid}/paper-probe")
    assert r.status_code == 200 and len(r.json()) == 1
