import os
import sys

import pytest
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


def test_vault_export_all_topics(session, tmp_path):
    app.dependency_overrides[get_session] = lambda: session
    for name in ("Build LLMs", "Learn Rust"):
        t = Topic(title=name)
        session.add(t)
        session.commit()
        session.refresh(t)
        session.add(Track(topic_id=t.id, title="tr", overview="ov"))
    session.commit()

    client = TestClient(app)
    r = client.post("/api/vault/export-all", json={"vault_path": str(tmp_path)})
    assert r.status_code == 200 and r.json()["topics"] == 2
    assert (tmp_path / "Adaptive Academy" / "build-llms" / "build-llms.md").exists()
    assert (tmp_path / "Adaptive Academy" / "learn-rust" / "learn-rust.md").exists()
    app.dependency_overrides.clear()


def test_vault_status_unconfigured():
    client = TestClient(app)
    st = client.get("/api/vault/status")
    assert st.status_code == 200 and st.json()["configured"] is False


@pytest.mark.skipif(
    sys.platform == "win32" or os.geteuid() == 0, reason="root ignores directory permissions"
)
@pytest.mark.parametrize("route", ["one", "all"])
def test_vault_export_to_unwritable_vault_says_why(session, tmp_path, route):
    """The container's uid may not own a bind-mounted vault: explain it, don't 500."""
    app.dependency_overrides[get_session] = lambda: session
    topic = Topic(title="Build LLMs")
    session.add(topic)
    session.commit()
    session.refresh(topic)
    vault = tmp_path / "vault"
    vault.mkdir()
    vault.chmod(0o555)
    try:
        client = TestClient(app)
        url = f"/api/topics/{topic.id}/vault/export" if route == "one" else "/api/vault/export-all"
        r = client.post(url, json={"vault_path": str(vault)})
    finally:
        vault.chmod(0o755)
        app.dependency_overrides.clear()
    assert r.status_code == 400
    detail = r.json()["detail"]
    assert "can't write to" in detail and "Permission denied" in detail
    assert f"uid {os.getuid()}" in detail and "AA_UID" in detail
