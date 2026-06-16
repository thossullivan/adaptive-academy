import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    Assessment, Concept, Item, Phase, Topic, Track,
)


def _seed(session, gaps):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    p = Phase(track_id=track.id, title="P0", position=0)
    session.add(p)
    session.commit()
    session.add(Item(phase_id=p.id, text="existing", type="read", status="todo", position=0))
    session.add(Assessment(concept_id=concept.id, kind="self_explanation", prompt="p",
                           score=0.3, gaps=gaps))
    session.commit()
    return topic.id, concept.id


def _override_llm(items):
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=json.dumps({"items": items, "revisit": None}))])


def test_remediate_happy_path_and_idempotent(session):
    app.dependency_overrides[get_session] = lambda: session
    topic_id, cid = _seed(session, ["gap A"])
    _override_llm([{"type": "build", "text": "attack A"}])
    client = TestClient(app)

    r = client.post(f"/api/concepts/{cid}/remediate", json={})
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 1 and body["items"][0]["is_remediation"] is True

    _override_llm([{"type": "build", "text": "again"}])
    r2 = client.post(f"/api/concepts/{cid}/remediate", json={})
    assert r2.status_code == 200 and r2.json()["items"] == []

    cur = client.get(f"/api/topics/{topic_id}/curriculum").json()
    flagged = [it for p in cur["phases"] for it in p["items"] if it["is_remediation"]]
    assert len(flagged) == 1
    app.dependency_overrides.clear()


def test_remediate_404_unknown_concept(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([])
    client = TestClient(app)
    assert client.post("/api/concepts/9999/remediate", json={}).status_code == 404
    app.dependency_overrides.clear()


def test_remediate_400_without_assessment(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([])
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="bare")
    session.add(concept)
    session.commit()
    client = TestClient(app)
    r = client.post(f"/api/concepts/{concept.id}/remediate", json={})
    assert r.status_code == 400
    app.dependency_overrides.clear()
