from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.models import Assessment, Concept, Topic, Track


def test_fleet_wind_and_comeback_endpoints(session):
    app.dependency_overrides[get_session] = lambda: session
    t = Topic(title="Build LLMs")
    session.add(t)
    session.commit()
    session.refresh(t)
    tr = Track(topic_id=t.id, title="tr")
    session.add(tr)
    session.commit()
    session.refresh(tr)
    c = Concept(track_id=tr.id, name="C")
    session.add(c)
    session.commit()
    session.refresh(c)
    # one qualifying assessment 12 days ago -> becalmed
    session.add(Assessment(concept_id=c.id, kind="self_explanation", prompt="",
                           created_at=datetime.utcnow() - timedelta(days=12)))
    session.commit()

    client = TestClient(app)

    fleet = client.get("/api/fleet")
    assert fleet.status_code == 200
    assert fleet.json()[0]["topic_title"] == "Build LLMs"

    wind = client.get(f"/api/topics/{t.id}/wind")
    assert wind.status_code == 200 and wind.json()["state"] == "becalmed"

    cb = client.get(f"/api/topics/{t.id}/comeback")
    assert cb.status_code == 200 and cb.json()["move"] is not None
    assert cb.json()["move"]["kind"] == "self_explain"
    app.dependency_overrides.clear()
