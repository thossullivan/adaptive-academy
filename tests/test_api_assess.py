import json

from fastapi.testclient import TestClient
from sqlmodel import select

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.engine import scout
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    Concept,
    KnowledgeEstimate,
    Milestone,
    Program,
    ProgramTopicLink,
    Topic,
    TopicFoundation,
    Track,
)


def _seed_concept(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["self-attention"], prerequisite_map={}))
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="self-attention")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high"))
    session.commit()
    return concept.id


def _llm():
    rubric = json.dumps({"criteria": ["c"], "must_include": ["softmax"],
                         "strong_signs": [], "weak_signs": [], "source_refs": []})
    grade = json.dumps({"score": 0.3, "verdict": "weak", "gaps": ["vague"]})
    return ScriptedLLMClient([LLMResponse(text=rubric), LLMResponse(text=grade)])


def test_assess_then_history(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: _llm()
    cid = _seed_concept(session)
    client = TestClient(app)

    r = client.post(f"/api/concepts/{cid}/assess",
                    json={"kind": "self_explanation", "response": "attention focuses"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["estimate_level"] == "low"  # 0.3 score, plus omitted "softmax"
    assert any("omitted" in g for g in body["gaps"])

    h = client.get(f"/api/concepts/{cid}/assessments")
    assert h.status_code == 200 and len(h.json()) == 1
    assert client.post("/api/concepts/9999/assess",
                       json={"kind": "self_explanation"}).status_code == 404
    app.dependency_overrides.clear()


def test_get_rubric_generates(session):
    app.dependency_overrides[get_session] = lambda: session
    rubric = json.dumps({"criteria": ["c"], "must_include": ["x"], "strong_signs": [],
                         "weak_signs": [], "source_refs": []})
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([LLMResponse(text=rubric)])
    cid = _seed_concept(session)
    client = TestClient(app)
    r = client.get(f"/api/concepts/{cid}/rubric")
    assert r.status_code == 200 and r.json()["must_include"] == ["x"]
    app.dependency_overrides.clear()


def test_assessment_succeeds_when_automatic_scout_raises(session, monkeypatch):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: _llm()
    concept_id = _seed_concept(session)
    concept = session.get(Concept, concept_id)
    track = session.get(Track, concept.track_id)
    program = Program(title="Research path")
    session.add(program)
    session.flush()
    milestone = Milestone(program_id=program.id, title="Foundations")
    session.add(milestone)
    session.flush()
    session.add(
        ProgramTopicLink(
            milestone_id=milestone.id,
            topic_id=track.topic_id,
            status="started",
            proposed_title="T",
        )
    )
    session.commit()
    calls: list[int] = []

    def raise_scout(_session, program_id, *, llm):
        calls.append(program_id)
        raise RuntimeError("scout unavailable")

    monkeypatch.setattr(scout, "maybe_scout", raise_scout)
    client = TestClient(app, raise_server_exceptions=False)

    response = client.post(
        f"/api/concepts/{concept_id}/assess",
        json={"kind": "self_explanation", "response": "attention focuses"},
    )

    assert response.status_code == 200, response.text
    assert calls == [program.id]
    assert session.exec(
        select(AgentEvent).where(AgentEvent.kind == "scout:error")
    ).one().program_id == program.id
    app.dependency_overrides.clear()
