import json

from fastapi.testclient import TestClient
from sqlmodel import Session

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_researcher, get_session
from adaptive_academy.llm.researcher_types import RawSource
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.scripted_researcher import ScriptedResearcherClient
from adaptive_academy.llm.types import LLMResponse


def _client(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    payload = json.dumps({"overview": "o", "key_concepts": ["self-attention"], "prerequisite_map": {}})
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient([LLMResponse(text=payload)])
    app.dependency_overrides[get_researcher] = lambda: ScriptedResearcherClient(
        {
            "foundational_papers": [
                RawSource(title="Attention", url="https://arxiv.org/abs/1706.03762", tier=1, relevance=0.95, summary="s"),
            ],
            "canonical_tutorials": [
                RawSource(title="Karpathy", url="https://youtube.com/watch?v=x", tier=2, relevance=0.8, summary="s"),
            ],
        }
    )
    return TestClient(app)


def test_research_review_roundtrip(session: Session):
    client = _client(session)
    tid = client.post("/api/topics", json={"title": "LLMs", "goal": "learn"}).json()["id"]

    r = client.post(f"/api/topics/{tid}/research")
    assert r.status_code == 200
    body = r.json()
    assert body["foundation"]["key_concepts"] == ["self-attention"]
    assert len(body["sources"]) == 2
    assert any(e["kind"] == "research:subagent" for e in body["events"])

    events = client.get(f"/api/topics/{tid}/events").json()
    assert len(events) > 0
    kinds = {e["kind"] for e in events}
    assert "research:subagent" in kinds
    assert "research:done" in kinds
    # each trace row carries its time, so the feed can show when a collapsed run last fired
    assert all(e["created_at"] for e in events)

    proposed = client.get(f"/api/topics/{tid}/sources?status=proposed").json()
    assert len(proposed) == 2
    keep_id = proposed[0]["id"]
    prune_id = proposed[1]["id"]

    rev = client.post(
        f"/api/topics/{tid}/sources/review",
        json={"accepted_ids": [keep_id], "pruned_ids": [prune_id]},
    )
    assert rev.status_code == 200
    statuses = {s["id"]: s["status"] for s in rev.json()}
    assert statuses[keep_id] == "accepted"
    assert statuses[prune_id] == "pruned"

    accepted = client.get(f"/api/topics/{tid}/sources?status=accepted").json()
    assert [s["id"] for s in accepted] == [keep_id]


def test_research_404_for_missing_topic(session: Session):
    client = _client(session)
    assert client.post("/api/topics/999/research").status_code == 404


def test_research_can_run_again_when_the_first_run_found_no_sources(session: Session):
    from sqlmodel import select

    from adaptive_academy.models import TopicFoundation

    client = _client(session)
    tid = client.post("/api/topics", json={"title": "LLMs", "goal": "learn"}).json()["id"]
    # A first run that saved a foundation but no sources (every search came back empty).
    session.add(TopicFoundation(topic_id=tid, overview="empty run", key_concepts=["x"],
                                prerequisite_map={}))
    session.commit()
    topic = client.get(f"/api/topics/{tid}").json()
    assert topic["has_foundation"] is True
    assert topic["can_research"] is True

    r = client.post(f"/api/topics/{tid}/research")

    assert r.status_code == 200
    assert len(r.json()["sources"]) == 2
    [fnd] = session.exec(select(TopicFoundation).where(TopicFoundation.topic_id == tid)).all()
    assert fnd.overview == "o"
    assert any(e["kind"] == "research:rerun" for e in r.json()["events"])
    # Now there is a reading list: research is done for this topic.
    assert client.get(f"/api/topics/{tid}").json()["can_research"] is False
    assert client.post(f"/api/topics/{tid}/research").status_code == 409


def test_topic_says_whether_research_is_running_now(session: Session):
    from adaptive_academy.engine.runlock import exclusive_run

    client = _client(session)
    tid = client.post("/api/topics", json={"title": "LLMs", "goal": "learn"}).json()["id"]
    assert client.get(f"/api/topics/{tid}").json()["research_running"] is False
    with exclusive_run(f"research:{tid}"):
        assert client.get(f"/api/topics/{tid}").json()["research_running"] is True
        assert client.get("/api/topics").json()[0]["research_running"] is True
    assert client.get(f"/api/topics/{tid}").json()["research_running"] is False
