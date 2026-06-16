import json

from fastapi.testclient import TestClient
from sqlmodel import select

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Concept, Item, KnowledgeEstimate, Phase, Topic, TopicFoundation, Track,
)


def test_weak_assessment_then_remediate_injects_targeted_item(session):
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="Build LLMs")
    session.add(topic)
    session.commit()
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["softmax"], prerequisite_map={}))
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    phase = Phase(track_id=track.id, title="P0", position=0)
    session.add(phase)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.6))
    session.add(Item(phase_id=phase.id, text="read about softmax", type="read",
                     status="todo", position=0))
    session.commit()
    client = TestClient(app)

    rubric = json.dumps({"criteria": ["c"], "must_include": ["subtract the max"],
                         "strong_signs": [], "weak_signs": [], "source_refs": []})
    grade = json.dumps({"score": 0.3, "verdict": "weak", "gaps": ["hand-wavy"]})
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=rubric), LLMResponse(text=grade)])
    a = client.post(f"/api/concepts/{concept.id}/assess",
                    json={"kind": "self_explanation", "response": "it normalizes"})
    assert a.status_code == 200 and a.json()["estimate_level"] == "low"

    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([LLMResponse(text=json.dumps(
        {"items": [{"type": "build", "text": "Implement numerically-stable softmax"}],
         "revisit": None}))])
    r = client.post(f"/api/concepts/{concept.id}/remediate", json={})
    # Two gaps drive remediation: the LLM's "hand-wavy" gap (covered by the scripted
    # draft item) plus a deterministic "omitted required element: subtract the max" gap
    # (the rubric's must_include the learner omitted -> auto-targeted item). Both are
    # legitimate remediation items, so the endpoint injects 2.
    assert r.status_code == 200 and len(r.json()["items"]) == 2

    items = session.exec(select(Item)).all()
    rem = [i for i in items if i.added_by == "remediation"]
    assert len(rem) == 2
    assert all("softmax" in i.concept_refs for i in rem)
    app.dependency_overrides.clear()
