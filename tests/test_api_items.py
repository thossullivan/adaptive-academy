# tests/test_api_items.py
from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.models import Item, Phase, Topic, Track


def test_patch_item_status(session):
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    phase = Phase(track_id=track.id, title="p", position=0)
    session.add(phase)
    session.commit()
    item = Item(phase_id=phase.id, text="x", type="read", position=0)
    session.add(item)
    session.commit()

    client = TestClient(app)
    r = client.patch(f"/api/items/{item.id}", json={"status": "done"})
    assert r.status_code == 200 and r.json()["status"] == "done"
    assert client.patch("/api/items/9999", json={"status": "done"}).status_code == 404
    # invalid status is rejected (and the item is left unchanged)
    assert client.patch(f"/api/items/{item.id}", json={"status": "bogus"}).status_code == 422
    session.refresh(item)
    assert item.status == "done"
    app.dependency_overrides.clear()
