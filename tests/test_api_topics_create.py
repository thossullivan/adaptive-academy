from fastapi.testclient import TestClient
from sqlmodel import Session

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_session


def _client(session: Session) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def test_create_topic_persists_intent(session: Session):
    client = _client(session)
    r = client.post(
        "/api/topics",
        json={"title": "Diffusion models", "goal": "grok score-based models", "prior_knowledge": "ML", "time_budget": "8h"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Diffusion models"
    assert body["intent"]["goal"] == "grok score-based models"
    assert body["has_foundation"] is False


def test_get_foundation_404_before_research(session: Session):
    client = _client(session)
    tid = client.post("/api/topics", json={"title": "T", "goal": "g"}).json()["id"]
    assert client.get(f"/api/topics/{tid}/foundation").status_code == 404
