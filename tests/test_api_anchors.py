import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_anchor_client, get_llm, get_session
from adaptive_academy.llm.anchor_types import RawAnchor
from adaptive_academy.llm.scripted_anchor import ScriptedAnchorClient
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Concept, KnowledgeEstimate, SourceDoc, Topic, TopicFoundation, Track,
)


def _seed(session):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["softmax"], prerequisite_map={}))
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
    src = SourceDoc(topic_id=topic.id, title="s", url="u", status="accepted")
    session.add(src)
    session.commit()
    return topic.id, concept.id, src.id


def test_generate_list_and_has_anchor(session):
    app.dependency_overrides[get_session] = lambda: session
    topic_id, cid, sid = _seed(session)
    app.dependency_overrides[get_anchor_client] = lambda: ScriptedAnchorClient({
        sid: [RawAnchor(question="why softmax?", reference_answer="ra",
                        key_points=["numerical stability"], concept_name="softmax")]})
    client = TestClient(app)

    gen = client.post(f"/api/topics/{topic_id}/anchors")
    assert gen.status_code == 200 and len(gen.json()["anchors"]) == 1

    lst = client.get(f"/api/concepts/{cid}/anchors")
    assert lst.status_code == 200 and len(lst.json()) == 1

    topic = client.get(f"/api/topics/{topic_id}").json()
    sm = [c for c in topic["concepts"] if c["id"] == cid][0]
    assert sm["has_anchor"] is True

    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps({"score": 0.8, "verdict": "ok", "gaps": [],
                                      "missing_required": [], "misconceptions_committed": []}))])
    a = client.post(f"/api/concepts/{cid}/assess",
                    json={"kind": "source_quiz", "response": "numerical stability matters"})
    assert a.status_code == 200
    app.dependency_overrides.clear()


def test_generate_400_without_sources(session):
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    app.dependency_overrides[get_anchor_client] = lambda: ScriptedAnchorClient({})
    client = TestClient(app)
    assert client.post(f"/api/topics/{topic.id}/anchors").status_code == 400
    app.dependency_overrides.clear()


def test_source_quiz_400_without_anchor(session):
    app.dependency_overrides[get_session] = lambda: session
    topic_id, cid, sid = _seed(session)
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([])
    client = TestClient(app)
    r = client.post(f"/api/concepts/{cid}/assess",
                    json={"kind": "source_quiz", "response": "x"})
    assert r.status_code == 400
    app.dependency_overrides.clear()
