"""Notebook routes: GET /api/concepts/{id}/notebook, PUT /api/concepts/{id}/note,
GET /api/topics/{id}/notebook, and the vault sync target (PUT /api/vault/sync, the `sync`
block on GET /api/vault/status). No model is called."""

import json
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.engine import backup, notebook_sync
from adaptive_academy.engine.notebook import NOTE_MAX_CHARS, START_MARKER
from adaptive_academy.engine.notebook_sync import NOTEBOOK_SYNC
from adaptive_academy.engine.vault import EXPORT_FOLDER
from adaptive_academy.models import (
    Assessment,
    Attempt,
    Concept,
    ConceptNote,
    Conversation,
    Message,
    Topic,
    Track,
)

T0 = datetime(2026, 10, 20, 9, 0)


@pytest.fixture
def client(session):
    NOTEBOOK_SYNC.reset()
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()
    NOTEBOOK_SYNC.reset()


def _seed(session):
    topic = Topic(title="Build LLMs")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="Self-Attention")
    session.add(concept)
    session.commit()
    return topic, concept


def test_notebook_shape(client, session):
    topic, concept = _seed(session)
    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()
    m = Message(conversation_id=convo.id, role="user", content="my try", is_attempt=True,
                created_at=T0)
    session.add(m)
    session.flush()
    session.add(Attempt(conversation_id=convo.id, concept_id=concept.id, message_id=m.id,
                        accepted=False, created_at=T0))
    session.add(Message(conversation_id=convo.id, role="tutor", content="worked", created_at=T0
                        + timedelta(minutes=1), reveals_solution=True))
    session.add(Assessment(concept_id=concept.id, kind="calibration", prompt="q", response="a",
                           score=0.4, gaps=["g"], verdict="v", created_at=T0 + timedelta(hours=1)))
    session.commit()

    empty = client.get(f"/api/concepts/{concept.id}/notebook").json()
    assert empty["note"] is None

    saved = client.put(f"/api/concepts/{concept.id}/note", json={"body": "Mine."})
    assert saved.status_code == 200
    assert saved.json()["body"] == "Mine." and saved.json()["concept_id"] == concept.id

    nb = client.get(f"/api/concepts/{concept.id}/notebook").json()
    assert nb["concept_id"] == concept.id and nb["concept_name"] == "Self-Attention"
    assert nb["topic_id"] == topic.id
    assert nb["note"]["body"] == "Mine." and nb["note"]["updated_at"]
    assert nb["counts"] == {"attempts": 1, "explanations": 1, "solutions": 1}
    explanation, solution, attempt = nb["items"]
    assert explanation == {
        "kind": "explanation", "id": explanation["id"], "created_at": explanation["created_at"],
        "source": "assess", "text": "a", "conversation_id": None, "accepted": None,
        "assessment_kind": "calibration", "label": "Calibration", "prompt": "q", "score": 0.4,
        "verdict": "v", "gaps": ["g"],
    }
    assert solution["kind"] == "solution" and solution["text"] == "worked"
    assert solution["conversation_id"] == convo.id
    assert attempt["kind"] == "attempt" and attempt["accepted"] is False


def test_notebook_404s(client, session):
    assert client.get("/api/concepts/999/notebook").status_code == 404
    assert client.put("/api/concepts/999/note", json={"body": "x"}).status_code == 404
    assert client.get("/api/topics/999/notebook").status_code == 404


def test_note_over_the_cap_is_a_clear_413_and_nothing_changes(client, session):
    _, concept = _seed(session)
    client.put(f"/api/concepts/{concept.id}/note", json={"body": "kept"})
    r = client.put(f"/api/concepts/{concept.id}/note", json={"body": "x" * (NOTE_MAX_CHARS + 1)})
    assert r.status_code == 413
    assert "50,000 characters" in r.json()["detail"]
    assert session.exec(select(ConceptNote)).one().body == "kept"


def test_topic_notebook_lists_concepts_with_notes_or_work(client, session):
    topic, concept = _seed(session)
    session.add(Concept(track_id=concept.track_id, name="Untouched"))
    session.commit()
    client.put(f"/api/concepts/{concept.id}/note", json={"body": "n"})
    r = client.get(f"/api/topics/{topic.id}/notebook")
    assert r.status_code == 200
    body = r.json()
    assert body["topic_id"] == topic.id
    assert [c["name"] for c in body["concepts"]] == ["Self-Attention"]
    row = body["concepts"][0]
    assert row["has_note"] is True and row["attempts"] == 0 and row["last_activity_at"]


def test_saving_a_note_with_a_vault_path_registers_it_and_syncs(client, session, tmp_path):
    (tmp_path / ".obsidian").mkdir()
    _, concept = _seed(session)
    r = client.put(f"/api/concepts/{concept.id}/note",
                   json={"body": "to the vault", "vault_path": str(tmp_path)})
    assert r.status_code == 200
    NOTEBOOK_SYNC.drain()
    note = tmp_path / EXPORT_FOLDER / "build-llms" / "Concepts" / "self-attention.md"
    assert "to the vault" in note.read_text()
    assert notebook_sync.sync_vault_path() == str(tmp_path.resolve())


def test_a_bad_vault_path_on_save_still_saves_the_note(client, session, tmp_path):
    _, concept = _seed(session)
    r = client.put(f"/api/concepts/{concept.id}/note",
                   json={"body": "safe", "vault_path": str(tmp_path / "missing")})
    assert r.status_code == 200
    assert session.exec(select(ConceptNote)).one().body == "safe"
    assert "does not exist" in NOTEBOOK_SYNC.status()["last_error"]


def test_vault_sync_target_and_status(client, session, tmp_path):
    (tmp_path / ".obsidian").mkdir()
    st = client.get("/api/vault/status").json()
    assert st["sync"]["path"] == "" and st["sync"]["last_error"] == ""

    r = client.put("/api/vault/sync", json={"vault_path": str(tmp_path)})
    assert r.status_code == 200 and r.json()["path"] == str(tmp_path.resolve())
    st = client.get("/api/vault/status", params={"vault_path": str(tmp_path)}).json()
    assert st["sync"]["path"] == str(tmp_path.resolve())

    bad = client.put("/api/vault/sync", json={"vault_path": str(tmp_path / "nope")})
    assert bad.status_code == 400
    assert notebook_sync.sync_vault_path() == str(tmp_path.resolve())  # unchanged

    cleared = client.put("/api/vault/sync", json={"vault_path": ""})
    assert cleared.status_code == 200 and cleared.json()["path"] == ""


def test_sync_errors_show_on_vault_status(client, session, tmp_path):
    (tmp_path / ".obsidian").mkdir()
    topic, concept = _seed(session)
    note = tmp_path / EXPORT_FOLDER / "build-llms" / "Concepts" / "self-attention.md"
    note.parent.mkdir(parents=True)
    note.write_text(f"{START_MARKER}\n")
    client.put("/api/vault/sync", json={"vault_path": str(tmp_path)})
    client.put(f"/api/concepts/{concept.id}/note", json={"body": "b"})
    NOTEBOOK_SYNC.drain()
    sync = client.get("/api/vault/status").json()["sync"]
    assert "self-attention.md" in sync["last_error"] and sync["last_error_at"]


def test_a_note_whose_section_was_edited_in_obsidian_is_named_as_locked(client, session, tmp_path):
    (tmp_path / ".obsidian").mkdir()
    _, concept = _seed(session)
    url = f"/api/concepts/{concept.id}/note"
    # No vault yet, then a vault with no note yet: nothing is locked, and nothing is made.
    assert client.get(f"/api/concepts/{concept.id}/notebook").json()["vault_locked_note"] is None
    client.put("/api/vault/sync", json={"vault_path": str(tmp_path)})
    assert client.get(f"/api/concepts/{concept.id}/notebook").json()["vault_locked_note"] is None
    assert not (tmp_path / EXPORT_FOLDER).exists()

    first = client.put(url, json={"body": "first"})
    assert first.status_code == 200 and first.json()["vault_locked_note"] is None
    NOTEBOOK_SYNC.drain()
    note = tmp_path / EXPORT_FOLDER / "build-llms" / "Concepts" / "self-attention.md"
    assert "first" in note.read_text()
    assert client.get(f"/api/concepts/{concept.id}/notebook").json()["vault_locked_note"] is None

    # Edited inside the section in Obsidian: the save is kept, the note is named as locked
    # (on the save itself, before the sync runs), and the sync leaves the note alone.
    edited = note.read_text().replace("first", "typed in Obsidian")
    note.write_text(edited)
    saved = client.put(url, json={"body": "second"})
    assert saved.status_code == 200
    assert saved.json()["body"] == "second"
    assert saved.json()["vault_locked_note"] == "self-attention.md"
    assert client.get(f"/api/concepts/{concept.id}/notebook").json()["vault_locked_note"] == (
        "self-attention.md")
    NOTEBOOK_SYNC.drain()
    assert note.read_text() == edited

    # Deleting the section (both markers) unlocks it: the next save writes it again.
    head, _, rest = edited.partition("<!-- adaptive-academy:notebook:start")
    note.write_text(head + rest.partition("<!-- adaptive-academy:notebook:end -->")[2])
    again = client.put(url, json={"body": "third"})
    assert again.json()["vault_locked_note"] is None
    NOTEBOOK_SYNC.drain()
    assert "third" in note.read_text()


def test_markers_that_dont_pair_up_are_not_reported_as_locked(client, session, tmp_path):
    (tmp_path / ".obsidian").mkdir()
    _, concept = _seed(session)
    note = tmp_path / EXPORT_FOLDER / "build-llms" / "Concepts" / "self-attention.md"
    note.parent.mkdir(parents=True)
    note.write_text(f"{START_MARKER}\n")
    client.put("/api/vault/sync", json={"vault_path": str(tmp_path)})
    r = client.put(f"/api/concepts/{concept.id}/note", json={"body": "b"})
    assert r.json()["vault_locked_note"] is None


def test_export_reports_problems(client, session, tmp_path):
    topic, concept = _seed(session)
    note = tmp_path / EXPORT_FOLDER / "build-llms" / "Concepts" / "self-attention.md"
    note.parent.mkdir(parents=True)
    note.write_text(f"{START_MARKER}\n")
    r = client.post(f"/api/topics/{topic.id}/vault/export", json={"vault_path": str(tmp_path)})
    assert r.status_code == 200
    assert len(r.json()["problems"]) == 1


def test_the_json_export_includes_concept_notes(session, tmp_path):
    db = tmp_path / "live.db"
    from sqlmodel import Session, SQLModel, create_engine

    engine = create_engine(f"sqlite:///{db}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        _, concept = _seed(s)
        s.add(ConceptNote(concept_id=concept.id, body="exported words"))
        s.commit()
    engine.dispose()

    out = backup.export_record(tmp_path / "out.json", database_url=f"sqlite:///{db}")
    tables = json.loads(out.read_text())["tables"]
    assert [r["body"] for r in tables["concept_note"]] == ["exported words"]

    snap = backup.snapshot(tmp_path / "snap.db", database_url=f"sqlite:///{db}")
    import sqlite3

    con = sqlite3.connect(snap)
    try:
        assert con.execute("SELECT body FROM concept_note").fetchall() == [("exported words",)]
    finally:
        con.close()


def test_sync_status_says_where_the_vault_comes_from(client, session, tmp_path, monkeypatch):
    from adaptive_academy.settings import settings

    assert client.get("/api/vault/status").json()["sync"]["source"] == ""
    monkeypatch.setattr(settings, "obsidian_vault_path", "/vault")
    st = client.get("/api/vault/status").json()
    assert st["sync"]["path"] == "/vault" and st["sync"]["source"] == "env"
    (tmp_path / ".obsidian").mkdir()
    assert client.put("/api/vault/sync", json={"vault_path": str(tmp_path)}).json()["source"] == (
        "browser")
    # Clearing the browser's path falls back to the env vault, and says so.
    cleared = client.put("/api/vault/sync", json={"vault_path": ""}).json()
    assert cleared["path"] == "/vault" and cleared["source"] == "env"


def test_exporting_a_topic_whose_folder_is_taken_is_a_400(client, session, tmp_path):
    topic, _ = _seed(session)
    root = tmp_path / EXPORT_FOLDER
    for stem, owner in (("build-llms", 998), (f"build-llms-{topic.id}", 999)):
        (root / stem).mkdir(parents=True)
        (root / stem / f"{stem}.md").write_text(f"---\ntitle: Other\ntopic_id: {owner}\n---\n")
    r = client.post(f"/api/topics/{topic.id}/vault/export", json={"vault_path": str(tmp_path)})
    assert r.status_code == 400 and "belongs to another topic" in r.json()["detail"]
    r = client.post("/api/vault/export-all", json={"vault_path": str(tmp_path)})
    assert r.status_code == 200 and len(r.json()["problems"]) == 1


def test_a_save_over_a_newer_note_is_a_409_with_that_note(client, session):
    _, concept = _seed(session)
    url = f"/api/concepts/{concept.id}/note"
    first = client.put(url, json={"body": "tab one", "base_updated_at": None})
    assert first.status_code == 200
    base = first.json()["updated_at"]
    # Another tab saves over it.
    other = client.put(url, json={"body": "tab two", "base_updated_at": base})
    assert other.status_code == 200
    # The first tab, still on the old version, is refused and told what is saved now.
    stale = client.put(url, json={"body": "tab one again", "base_updated_at": base})
    assert stale.status_code == 409
    assert "saved somewhere else" in stale.json()["detail"]
    assert stale.json()["note"]["body"] == "tab two"
    assert session.exec(select(ConceptNote)).one().body == "tab two"
    # Keep my draft: resend on the version it was told about.
    kept = client.put(url, json={"body": "tab one again",
                                 "base_updated_at": stale.json()["note"]["updated_at"]})
    assert kept.status_code == 200 and kept.json()["body"] == "tab one again"
    # "No note yet" when there is one is a conflict too.
    assert client.put(url, json={"body": "x", "base_updated_at": None}).status_code == 409


def test_a_save_without_a_base_is_not_checked(client, session):
    _, concept = _seed(session)
    url = f"/api/concepts/{concept.id}/note"
    client.put(url, json={"body": "one"})
    assert client.put(url, json={"body": "two"}).status_code == 200
    assert session.exec(select(ConceptNote)).one().body == "two"
