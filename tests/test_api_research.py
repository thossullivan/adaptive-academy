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
