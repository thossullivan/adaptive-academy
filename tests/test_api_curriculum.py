# tests/test_api_curriculum.py
import json

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import SourceDoc, TopicFoundation, TopicIntent


def _client(session):
    app.dependency_overrides[get_session] = lambda: session
    payload = json.dumps({
        "overview": "ov",
        "phases": [{"title": "P1", "est_hours": "Wk1",
                    "items": [{"type": "read", "text": "paper", "concept_refs": ["la"]}],
                    "deliverable": {"kind": "blog", "text": "post",
                                    "acceptance_criteria": ["clear"]}}],
        "sidebars": [{"kind": "reference", "title": "Ref", "body": "b"}],
    })
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([LLMResponse(text=payload)])
    return TestClient(app)


def _seed_topic(session):
    from adaptive_academy.models import Topic
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    session.add(TopicIntent(topic_id=topic.id, goal="g"))
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["self-attention", "la"],
                prerequisite_map={"self-attention": ["la"]}))
    session.add(SourceDoc(topic_id=topic.id, title="S", url="u", tier=1,
                status="accepted"))
    session.commit()
    return topic.id


def test_generate_then_get_and_export(session):
    client = _client(session)
    tid = _seed_topic(session)

    r = client.post(f"/api/topics/{tid}/curriculum")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["track"]["overview"] == "ov"
    assert body["phases"][0]["deliverable"]["kind"] == "blog"
    assert any(c["name"] == "la" and c["is_load_bearing"] for c in body["concepts"])
    assert body["events"]

    r2 = client.get(f"/api/topics/{tid}/curriculum")
    assert r2.status_code == 200 and r2.json()["phases"][0]["title"] == "P1"

    r3 = client.get(f"/api/topics/{tid}/curriculum.md")
    assert r3.status_code == 200 and "## Phase 1 — P1" in r3.text

    app.dependency_overrides.clear()


def test_generate_400_without_foundation_or_accepted(session):
    from adaptive_academy.models import Topic
    client = _client(session)
    topic = Topic(title="bare")
    session.add(topic)
    session.commit()
    session.add(TopicIntent(topic_id=topic.id, goal="g"))
    session.commit()
    r = client.post(f"/api/topics/{topic.id}/curriculum")
    assert r.status_code == 400
    app.dependency_overrides.clear()


def test_generate_400_with_foundation_but_no_accepted_sources(session):
    # Foundation present, but the reading list was never accepted -> distinct 400.
    from adaptive_academy.models import Topic
    client = _client(session)
    topic = Topic(title="unreviewed")
    session.add(topic)
    session.commit()
    session.add(TopicIntent(topic_id=topic.id, goal="g"))
    session.add(TopicFoundation(topic_id=topic.id, overview="o",
                key_concepts=["la"], prerequisite_map={}))
    session.add(SourceDoc(topic_id=topic.id, title="S", url="u", tier=1, status="proposed"))
    session.commit()
    r = client.post(f"/api/topics/{topic.id}/curriculum")
    assert r.status_code == 400
    assert "accepted" in r.json()["detail"]
    app.dependency_overrides.clear()


def test_import_after_generate_replaces_track_without_crashing(session):
    # Policy: import replaces phases/items/sidebars only. Concepts, estimates, and
    # concept edges are competence evidence + graph history and survive a re-import
    # (generate -> export -> edit -> re-import is the normal flow).
    from sqlmodel import select

    from adaptive_academy.models import Concept, ConceptEdge, KnowledgeEstimate, Track

    client = _client(session)
    tid = _seed_topic(session)
    assert client.post(f"/api/topics/{tid}/curriculum").status_code == 200
    md = client.get(f"/api/topics/{tid}/curriculum.md").text
    concept_ids = {
        c.id for c in session.exec(select(Concept).join(Track).where(Track.topic_id == tid))
    }
    estimates_before = len(session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id.in_(concept_ids))
    ).all())
    edges_before = len(session.exec(
        select(ConceptEdge).where(ConceptEdge.src_concept_id.in_(concept_ids))
    ).all())

    r = client.post(f"/api/topics/{tid}/curriculum/import", json={"markdown": md})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["phases"][0]["title"] == "P1"
    # exactly one track remains for the topic, and it kept its concepts
    tracks = session.exec(select(Track).where(Track.topic_id == tid)).all()
    assert len(tracks) == 1
    assert {
        c.id for c in session.exec(select(Concept).where(Concept.track_id == tracks[0].id))
    } == concept_ids
    assert len(session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id.in_(concept_ids))
    ).all()) == estimates_before
    assert len(session.exec(
        select(ConceptEdge).where(ConceptEdge.src_concept_id.in_(concept_ids))
    ).all()) == edges_before
    r2 = client.get(f"/api/topics/{tid}/curriculum")
    assert r2.status_code == 200
    app.dependency_overrides.clear()
