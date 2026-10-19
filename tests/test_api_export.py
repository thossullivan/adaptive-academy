"""GET /api/export/{backup,record}: container users download their learning record."""

import json
import re
import sqlite3
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine

from adaptive_academy.api.app import app
from adaptive_academy.engine import backup
from adaptive_academy.models import Topic


@pytest.fixture
def file_db(tmp_path, monkeypatch):
    path = tmp_path / "adaptive_academy.db"
    engine = create_engine(f"sqlite:///{path}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(Topic(title="Linear algebra"))
        session.commit()
    engine.dispose()
    monkeypatch.setattr(backup.settings, "database_url", f"sqlite:///{path}")
    return path


@pytest.fixture
def scratch_tmp(tmp_path, monkeypatch):
    """Point tempfile at an observable dir so the test can see the temp files cleaned up."""
    scratch = tmp_path / "tmp"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    return scratch


@pytest.fixture
def client():
    return TestClient(app)


def _attachment_name(response) -> str:
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment")
    match = re.search(r'filename="([^"]+)"', disposition)
    assert match, disposition
    return match.group(1)


def test_backup_download_is_a_valid_sqlite_snapshot(client, file_db, scratch_tmp, tmp_path):
    response = client.get("/api/export/backup")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/vnd.sqlite3"
    name = _attachment_name(response)
    assert re.fullmatch(r"adaptive_academy-\d{8}-\d{6}\.db", name)
    assert response.content.startswith(b"SQLite format 3\x00")
    downloaded = tmp_path / "downloaded.db"
    downloaded.write_bytes(response.content)
    conn = sqlite3.connect(downloaded)
    try:
        assert conn.execute("SELECT title FROM topic").fetchall() == [("Linear algebra",)]
    finally:
        conn.close()
    assert list(scratch_tmp.iterdir()) == [], "temp snapshot must be removed after the response"


def test_record_download_is_the_json_export(client, file_db, scratch_tmp):
    response = client.get("/api/export/record")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    name = _attachment_name(response)
    assert re.fullmatch(r"adaptive_academy-\d{8}-\d{6}\.json", name)
    doc = json.loads(response.content)
    assert doc["format"] == "adaptive-academy-export"
    assert doc["version"] == 1
    assert [t["title"] for t in doc["tables"]["topic"]] == ["Linear algebra"]
    assert list(scratch_tmp.iterdir()) == []


@pytest.mark.parametrize("endpoint", ["/api/export/backup", "/api/export/record"])
def test_non_sqlite_database_is_a_legible_error(client, monkeypatch, scratch_tmp, endpoint):
    monkeypatch.setattr(backup.settings, "database_url", "postgresql://localhost/aa")
    response = client.get(endpoint)
    assert response.status_code == 500
    assert "SQLite" in response.json()["detail"]
    assert list(scratch_tmp.iterdir()) == []


def test_export_does_not_widen_cors(client, file_db):
    response = client.get("/api/export/backup", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in response.headers


def test_temp_dir_never_lands_in_repo(file_db, scratch_tmp):
    """Sanity: the fixture redirect actually took (else the cleanup asserts prove nothing)."""
    assert Path(tempfile.gettempdir()) == scratch_tmp


# --- the scratch copy is removed however the response ends -----------------------------
# Starlette's FileResponse returns early for a bad / unsatisfiable Range header and skips
# its BackgroundTask, and a client disconnect aborts the send; any of those used to leave
# an aa-download-* dir holding a full copy of the db.


@pytest.mark.parametrize("endpoint", ["/api/export/backup", "/api/export/record"])
@pytest.mark.parametrize(("range_header", "status"), [
    ("bytes=abc", 400),
    ("bytes=999999999-", 416),
])
def test_bad_range_leaves_no_temp_copy(client, file_db, scratch_tmp, endpoint,
                                       range_header, status):
    response = client.get(endpoint, headers={"Range": range_header})
    assert response.status_code == status
    assert list(scratch_tmp.iterdir()) == []


def test_satisfiable_range_still_works_and_cleans_up(client, file_db, scratch_tmp):
    response = client.get("/api/export/backup", headers={"Range": "bytes=0-15"})
    assert response.status_code == 206
    assert response.content == b"SQLite format 3\x00"
    assert list(scratch_tmp.iterdir()) == []


def test_client_disconnect_mid_download_leaves_no_temp_copy(file_db, scratch_tmp):
    import anyio

    from adaptive_academy.api.routes_export import download_backup

    response = download_backup()

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            raise OSError("client went away")

    scope = {"type": "http", "method": "GET", "headers": [], "extensions": {}}
    with pytest.raises(OSError):
        anyio.run(response, scope, receive, send)
    assert list(scratch_tmp.iterdir()) == []


def test_pathsend_is_not_used_for_the_scratch_copy(file_db, scratch_tmp):
    """With http.response.pathsend the server reads the file after the app returns, by
    which time the scratch dir is gone, so the download streams the bytes itself."""
    import anyio

    from adaptive_academy.api.routes_export import download_backup

    response = download_backup()
    sent = []

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        sent.append(message)

    scope = {"type": "http", "method": "GET", "headers": [],
             "extensions": {"http.response.pathsend": {}}}
    anyio.run(response, scope, receive, send)
    assert not any(m["type"] == "http.response.pathsend" for m in sent)
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    assert body.startswith(b"SQLite format 3\x00")
    assert list(scratch_tmp.iterdir()) == []


def test_check_is_ok_for_an_exportable_db_and_writes_nothing(client, file_db, scratch_tmp):
    # The page calls this before handing the download to the browser, so a big file streams
    # to disk instead of being buffered in the tab.
    r = client.get("/api/export/check")
    assert r.status_code == 200
    assert r.json() == {"ok": True}
    assert list(scratch_tmp.iterdir()) == []


def test_check_gives_the_legible_error_for_a_non_sqlite_db(client, monkeypatch):
    monkeypatch.setattr(backup.settings, "database_url", "postgresql://localhost/aa")
    r = client.get("/api/export/check")
    assert r.status_code == 500
    assert "SQLite" in r.json()["detail"]


def test_check_gives_the_legible_error_for_a_missing_db(client, monkeypatch, tmp_path):
    monkeypatch.setattr(backup.settings, "database_url", f"sqlite:///{tmp_path / 'nope.db'}")
    r = client.get("/api/export/check")
    assert r.status_code == 500
    assert "does not exist" in r.json()["detail"]
    assert not (tmp_path / "nope.db").exists()
