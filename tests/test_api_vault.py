from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.models import Concept, Topic, Track


def test_vault_status_export_ingest_roundtrip(session, tmp_path):
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="Build LLMs")
    session.add(topic)
    session.commit()
    session.refresh(topic)
    track = Track(topic_id=topic.id, title="tr", overview="ov")
    session.add(track)
    session.commit()
    session.refresh(track)
    session.add(Concept(track_id=track.id, name="Self-Attention"))
    session.commit()

    client = TestClient(app)

    # status on an empty vault dir
    st = client.get("/api/vault/status", params={"vault_path": str(tmp_path)})
    assert st.status_code == 200 and st.json()["is_dir"] is True

    # export writes the hub + concept note
    ex = client.post(f"/api/topics/{topic.id}/vault/export", json={"vault_path": str(tmp_path)})
    assert ex.status_code == 200
    assert any(w.endswith("build-llms.md") for w in ex.json()["written"])
    assert (tmp_path / "Adaptive Academy" / "build-llms" / "build-llms.md").exists()

    # a stray learner note → ingest registers it as a source; our export folder is skipped
    (tmp_path / "my-notes.md").write_text("# My Notes\n\nSome material.")
    ing = client.post(f"/api/topics/{topic.id}/vault/ingest", json={"vault_path": str(tmp_path)})
    assert ing.status_code == 200
    assert ing.json()["count"] == 1 and ing.json()["titles"] == ["My Notes"]

    # a missing path is a 400, not a 500
    bad = client.post(f"/api/topics/{topic.id}/vault/export",
                      json={"vault_path": str(tmp_path / "nope")})
    assert bad.status_code == 400
    app.dependency_overrides.clear()


def test_vault_status_unconfigured():
    client = TestClient(app)
    st = client.get("/api/vault/status")
    assert st.status_code == 200 and st.json()["configured"] is False
