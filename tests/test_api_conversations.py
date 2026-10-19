import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_retriever, get_session
from adaptive_academy.engine.memory import index_text
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
from adaptive_academy.llm.types import LLMResponse, ToolCall
from adaptive_academy.models import Chunk, Concept, KnowledgeEstimate, Topic, Track


@pytest.fixture
def client():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        topic = Topic(title="LLMs")
        s.add(topic)
        s.commit()
        track = Track(topic_id=topic.id, title="Core")
        s.add(track)
        s.commit()
        concept = Concept(track_id=track.id, name="self-attention")
        s.add(concept)
        s.commit()
        s.add(KnowledgeEstimate(concept_id=concept.id, level="high"))
        s.commit()
        topic_id, concept_id = topic.id, concept.id

    def _session_override():
        with Session(engine) as s:
            yield s

    scripted = ScriptedLLMClient([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="reveal_solution",
                                         input={"text": "SECRET"})]),
        LLMResponse(text="Hint: what does softmax normalize?"),
    ])

    app = create_app()
    retriever = ScriptedRetriever()
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_llm] = lambda: scripted
    app.dependency_overrides[get_retriever] = lambda: retriever
    c = TestClient(app)
    c.engine = engine
    c.topic_id, c.concept_id, c.retriever = topic_id, concept_id, retriever
    yield c
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/api/health").json() == {"status": "ok"}


def test_send_message_blocks_reveal_before_attempt(client):
    start = client.post(
        "/api/conversations",
        json={"topic_id": client.topic_id, "concept_id": client.concept_id},
    ).json()
    assert start["assistance_level"] == "low"
    assert start["challenge_level"] == "high"

    resp = client.post(
        f"/api/conversations/{start['id']}/messages",
        json={"content": "just give me the answer"},
    ).json()

    assert "SECRET" not in resp["reply"]
    assert resp["attempt_logged"] is False
    assert any("reveal_solution:blocked" in e["kind"] for e in resp["events"])
    assert resp["memory"] == []


def test_send_message_returns_retrieved_memory(client):
    with Session(client.engine) as session:
        index_text(
            session,
            kind="vault_note",
            text="Self-attention uses softmax to weight token interactions.",
            source_ref="file:///vault/attention.md",
            doc_title="Attention",
            topic_id=client.topic_id,
            concept_id=client.concept_id,
            heading="Weights",
        )
        session.commit()
        chunk = session.exec(
            select(Chunk).where(Chunk.source_ref == "file:///vault/attention.md")
        ).one()
        client.retriever.hits = {
            "self-attention Explain softmax attention": [chunk.id]
        }

    start = client.post(
        "/api/conversations",
        json={"topic_id": client.topic_id, "concept_id": client.concept_id},
    ).json()
    response = client.post(
        f"/api/conversations/{start['id']}/messages",
        json={"content": "Explain softmax attention"},
    )

    assert response.status_code == 200
    assert response.json()["memory"] == [
        {
            "chunk_id": response.json()["memory"][0]["chunk_id"],
            "kind": "vault_note",
            "heading": "Weights",
            "snippet": "Self-attention uses softmax to weight token interactions.",
            "score": 1.0,
            "source_ref": "file:///vault/attention.md",
        }
    ]


def test_start_conversation_rejects_concept_from_another_topic(session):
    from fastapi.testclient import TestClient

    from adaptive_academy.api.app import create_app
    from adaptive_academy.api.deps import get_session
    from adaptive_academy.models import Concept, Topic, Track

    topic_a = Topic(title="A")
    topic_b = Topic(title="B")
    session.add(topic_a)
    session.add(topic_b)
    session.commit()
    track = Track(topic_id=topic_a.id, title="A")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="Owned by A")
    session.add(concept)
    session.commit()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    wrong = client.post("/api/conversations", json={"topic_id": topic_b.id, "concept_id": concept.id})
    right = client.post("/api/conversations", json={"topic_id": topic_a.id, "concept_id": concept.id})
    missing = client.post("/api/conversations", json={"topic_id": topic_a.id, "concept_id": 99999})
    app.dependency_overrides.clear()
    assert wrong.status_code == 400
    assert right.status_code == 200
    assert missing.status_code == 404


def _conversation_count(engine) -> int:
    from adaptive_academy.models import Conversation

    with Session(engine) as s:
        return len(s.exec(select(Conversation)).all())


def test_preview_returns_levels_without_creating_a_conversation(client):
    resp = client.get(
        "/api/conversations/preview",
        params={"topic_id": client.topic_id, "concept_id": client.concept_id},
    )
    assert resp.status_code == 200
    # Same levels a started conversation would report (estimate "high"); a new session
    # never starts with an attempt logged.
    assert resp.json() == {
        "concept_id": client.concept_id,
        "assistance_level": "low",
        "challenge_level": "high",
        "attempt_logged": False,
    }
    assert _conversation_count(client.engine) == 0


def test_preview_matches_started_conversation_levels(client):
    preview = client.get(
        "/api/conversations/preview",
        params={"topic_id": client.topic_id, "concept_id": client.concept_id},
    ).json()
    started = client.post(
        "/api/conversations",
        json={"topic_id": client.topic_id, "concept_id": client.concept_id},
    ).json()
    for key in ("concept_id", "assistance_level", "challenge_level", "attempt_logged"):
        assert preview[key] == started[key]
    assert _conversation_count(client.engine) == 1


def test_preview_validates_concept_and_topic(session):
    from fastapi.testclient import TestClient

    from adaptive_academy.api.app import create_app
    from adaptive_academy.api.deps import get_session

    topic_a = Topic(title="A")
    topic_b = Topic(title="B")
    session.add(topic_a)
    session.add(topic_b)
    session.commit()
    track = Track(topic_id=topic_a.id, title="A")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="Owned by A")
    session.add(concept)
    session.commit()

    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    url = "/api/conversations/preview"
    wrong = client.get(url, params={"topic_id": topic_b.id, "concept_id": concept.id})
    right = client.get(url, params={"topic_id": topic_a.id, "concept_id": concept.id})
    missing = client.get(url, params={"topic_id": topic_a.id, "concept_id": 99999})
    app.dependency_overrides.clear()
    assert wrong.status_code == 400
    assert missing.status_code == 404
    assert right.status_code == 200
    # No estimate yet: the default levels compute_levels picks.
    assert right.json()["assistance_level"] == "low"
    assert right.json()["challenge_level"] == "high"
