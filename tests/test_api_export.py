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
