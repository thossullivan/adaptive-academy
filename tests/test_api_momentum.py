from datetime import datetime, timedelta

from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.models import Assessment, Concept, Item, Phase, Topic, Track


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
    # one qualifying assessment 12 days ago -> becalmed; the lone concept is assessed -> 100% covered
    session.add(Assessment(concept_id=c.id, kind="self_explanation", prompt="",
                           created_at=datetime.utcnow() - timedelta(days=12)))
    # an undone curriculum item so the comeback move has somewhere to point
    phase = Phase(track_id=tr.id, title="P1", position=0)
    session.add(phase)
    session.commit()
    session.refresh(phase)
    session.add(Item(phase_id=phase.id, text="b", position=0, status="todo"))
    session.commit()

    client = TestClient(app)

    fleet = client.get("/api/fleet")
    assert fleet.status_code == 200
    assert fleet.json()[0]["topic_title"] == "Build LLMs"
    assert fleet.json()[0]["progress"] == 1.0  # the topic's 1 concept is assessed

    wind = client.get(f"/api/topics/{t.id}/wind")
    assert wind.status_code == 200 and wind.json()["state"] == "becalmed"
    assert wind.json()["progress"] == 1.0

    cb = client.get(f"/api/topics/{t.id}/comeback")
    assert cb.status_code == 200 and cb.json()["move"] is not None
    # becalmed with an undone curriculum item -> the comeback points at that item
    assert cb.json()["move"]["label"] == "b"
    assert cb.json()["move"]["href"] == f"/topics/{t.id}/track"
    app.dependency_overrides.clear()
