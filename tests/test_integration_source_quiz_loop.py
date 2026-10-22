import json

from fastapi.testclient import TestClient
from sqlmodel import select

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_anchor_client, get_llm, get_session
from adaptive_academy.llm.anchor_types import RawAnchor
from adaptive_academy.llm.scripted_anchor import ScriptedAnchorClient
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, KnowledgeEstimate, SourceDoc, Topic, TopicFoundation, Track,
)


def test_generate_anchor_then_source_quiz_updates_estimate(session):
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="Build LLMs")
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
    client = TestClient(app)

    app.dependency_overrides[get_anchor_client] = lambda: ScriptedAnchorClient({
        src.id: [RawAnchor(question="Why subtract the max?", reference_answer="stability",
                           key_points=["numerical stability"], concept_name="softmax")]})
    gen = client.post(f"/api/topics/{topic.id}/anchors")
    assert gen.status_code == 200 and len(gen.json()["anchors"]) == 1

    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps({"score": 0.2, "verdict": "weak", "gaps": [],
                                      "missing_required": [], "misconceptions_committed": []}))])
    a = client.post(f"/api/concepts/{concept.id}/assess",
                    json={"kind": "source_quiz", "response": "no idea"})
    assert a.status_code == 200 and a.json()["estimate_level"] == "low"

    rows = session.exec(select(Assessment)).all()
    assert rows[-1].anchor_id is not None
    app.dependency_overrides.clear()
