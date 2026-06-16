# tests/test_integration_assess_loop.py
import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Concept, KnowledgeEstimate, Topic, TopicFoundation, Track,
)


def test_weak_assessment_raises_tutor_assistance(session):
    app.dependency_overrides[get_session] = lambda: session
    # Seed a generated-style concept at high knowledge (assistance starts low).
    topic = Topic(title="Build LLMs")
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
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
    session.commit()

    client = TestClient(app)
    convo = client.post("/api/conversations",
                        json={"topic_id": topic.id, "concept_id": concept.id}).json()
    assert convo["assistance_level"] == "low"  # expert default

    # A weak, anchored assessment: rubric requires "softmax"; learner omits it; LLM low score.
    rubric = json.dumps({"criteria": ["c"], "must_include": ["softmax"],
                         "strong_signs": [], "weak_signs": [], "source_refs": []})
    grade = json.dumps({"score": 0.3, "verdict": "weak", "gaps": ["vague"]})
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=rubric), LLMResponse(text=grade)])
    a = client.post(f"/api/concepts/{concept.id}/assess",
                    json={"kind": "self_explanation", "response": "it focuses on things"})
    assert a.status_code == 200 and a.json()["estimate_level"] == "low"

    # The Tutor lever moved: a fresh conversation now opens at high assistance.
    convo2 = client.post("/api/conversations",
                         json={"topic_id": topic.id, "concept_id": concept.id}).json()
    assert convo2["assistance_level"] == "high"
    app.dependency_overrides.clear()
