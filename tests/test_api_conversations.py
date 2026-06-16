import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse, ToolCall
from adaptive_academy.models import Concept, Conversation, KnowledgeEstimate, Topic, Track


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
    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_llm] = lambda: scripted
    c = TestClient(app)
    c.topic_id, c.concept_id = topic_id, concept_id
    return c


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
