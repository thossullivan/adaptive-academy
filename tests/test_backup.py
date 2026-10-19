"""Backup, JSON export, and restore of the learning record (engine/backup.py + `aa` CLI).

The shared `session` fixture is in-memory; everything here needs a real WAL-mode file db,
so `live_db` builds one in tmp_path and leaves uncheckpointed writes in its -wal file.
"""

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine

from adaptive_academy import cli
from adaptive_academy.db import ensure_fts, ensure_vec
from adaptive_academy.engine import backup
from adaptive_academy.models import AgentEvent, Assessment, Concept, Topic, Track

REVISION = "test0revision"
WHEN = datetime(2026, 10, 19, 12, 30, 45, 123456, tzinfo=timezone.utc)


def _sqlite_header_journal_byte(path: Path) -> int:
    """Byte 18 of the SQLite header: 1 = rollback journal (self-contained), 2 = WAL."""
    return path.read_bytes()[18]


@pytest.fixture
def live_db(tmp_path):
    """A populated WAL-mode file db whose latest writes still sit in the -wal file.

    The engine stays open (yielded) so the WAL is not checkpointed away on close, which is
    exactly the state a running app leaves the db in.
    """
    path = tmp_path / "live" / "adaptive_academy.db"
    path.parent.mkdir()
    url = f"sqlite:///{path}"
    engine = create_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _pragma(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA wal_autocheckpoint=0")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    ensure_fts(engine)
    ensure_vec(engine)  # creates the chunk_vec virtual table when sqlite-vec is installed
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(32) NOT NULL)"))
        connection.execute(text("INSERT INTO alembic_version VALUES (:v)"), {"v": REVISION})
    with Session(engine) as session:
        topic = Topic(title="Linear algebra", created_at=WHEN)
        session.add(topic)
        session.flush()
        track = Track(topic_id=topic.id, title="Spectral")
        session.add(track)
        session.flush()
        concept = Concept(track_id=track.id, name="Eigenvectors")
        session.add(concept)
        session.flush()
        session.add(
            Assessment(
                concept_id=concept.id,
                kind="self_explanation",
                prompt="Why do eigenvectors matter?",
                score=0.75,
                gaps=["orthogonality"],
                created_at=WHEN,
            )
        )
        session.add(AgentEvent(kind="test", detail="ünïcode ✓", topic_id=topic.id))
        session.commit()
    wal = Path(f"{path}-wal")
    assert wal.exists() and wal.stat().st_size > 0, "fixture must leave uncheckpointed writes"
    yield path, url
    engine.dispose()


# --- path resolution ---------------------------------------------------------------------


def test_sqlite_path_resolves_file_urls(tmp_path):
    assert backup.sqlite_path(f"sqlite:///{tmp_path}/a.db") == tmp_path / "a.db"
    assert backup.sqlite_path("sqlite:///./rel.db") == Path.cwd() / "rel.db"


@pytest.mark.parametrize(
    "url",
    ["postgresql://user@localhost/aa", "mysql://localhost/aa", "sqlite://", "sqlite:///:memory:"],
)
def test_non_file_sqlite_url_is_a_clear_error(url):
    with pytest.raises(backup.BackupError, match="SQLite"):
        backup.sqlite_path(url)


def test_snapshot_of_missing_db_is_a_clear_error(tmp_path):
    with pytest.raises(backup.BackupError, match="does not exist"):
        backup.snapshot(tmp_path / "out.db", database_url=f"sqlite:///{tmp_path}/nope.db")
    assert not (tmp_path / "nope.db").exists(), "must not create an empty db as a side effect"


# --- snapshot -----------------------------------------------------------------------------


def test_snapshot_is_one_self_contained_file_with_uncheckpointed_rows(live_db, tmp_path):
    _, url = live_db
    dest = tmp_path / "out" / "snap.db"
    dest.parent.mkdir()

    result = backup.snapshot(dest, database_url=url)

    assert result == dest
    assert sorted(p.name for p in dest.parent.iterdir()) == ["snap.db"], "no -wal/-shm/partial"
    assert _sqlite_header_journal_byte(dest) == 1, "snapshot must not depend on a WAL file"
    conn = sqlite3.connect(dest)
    try:
        assert conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        assert conn.execute("SELECT title FROM topic").fetchall() == [("Linear algebra",)]
        assert conn.execute("SELECT count(*) FROM assessment").fetchone()[0] == 1
        assert conn.execute("SELECT version_num FROM alembic_version").fetchone()[0] == REVISION
    finally:
        conn.close()
    assert sorted(p.name for p in dest.parent.iterdir()) == ["snap.db"]


def test_snapshot_refuses_to_overwrite(live_db, tmp_path):
    _, url = live_db
    dest = tmp_path / "exists.db"
    dest.write_bytes(b"keep me")
    with pytest.raises(backup.BackupError, match="already exists"):
        backup.snapshot(dest, database_url=url)
    assert dest.read_bytes() == b"keep me"


def test_default_names_are_timestamped():
    now = datetime(2026, 1, 2, 3, 4, 5)
    assert backup.default_name("db", now) == "adaptive_academy-20260102-030405.db"
    assert backup.default_name("json", now) == "adaptive_academy-20260102-030405.json"


# --- JSON export --------------------------------------------------------------------------


def _export(url: str, dest: Path) -> dict:
    backup.export_record(dest, database_url=url)
    return json.loads(dest.read_text(encoding="utf-8"))


def test_export_covers_every_metadata_table(live_db, tmp_path):
    _, url = live_db
    doc = _export(url, tmp_path / "record.json")

    assert doc["format"] == "adaptive-academy-export"
    assert doc["version"] == 1
    assert doc["schema_revision"] == REVISION
    datetime.fromisoformat(doc["exported_at"])
    expected = {t.name for t in SQLModel.metadata.sorted_tables} - set(backup.EXCLUDED_TABLES)
    assert set(doc["tables"]) == expected
    assert all(isinstance(rows, list) for rows in doc["tables"].values())


def test_export_excludes_derived_search_indexes(live_db, tmp_path):
    path, url = live_db
    conn = sqlite3.connect(path)
    try:
        in_db = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()
    assert "chunk_fts" in in_db  # the index really exists, so its absence below means something
    doc = _export(url, tmp_path / "record.json")
    assert {"chunk_fts", "chunk_vec"} <= set(backup.EXCLUDED_TABLES)
    assert set(doc["excluded_tables"]) == set(backup.EXCLUDED_TABLES)
    for name in doc["tables"]:
        assert not name.startswith(("chunk_fts", "chunk_vec")), name
    assert "alembic_version" not in doc["tables"]


def test_export_rows_round_trip_with_iso_datetimes_and_json_columns(live_db, tmp_path):
    _, url = live_db
    doc = _export(url, tmp_path / "record.json")

    [topic] = doc["tables"]["topic"]
    assert topic["title"] == "Linear algebra"
    assert datetime.fromisoformat(topic["created_at"]) == WHEN.replace(tzinfo=None)
    [assessment] = doc["tables"]["assessment"]
    assert assessment["gaps"] == ["orthogonality"]  # JSON column stays structured
    assert assessment["score"] == 0.75
    [agent_event] = doc["tables"]["agentevent"]
    assert agent_event["detail"] == "ünïcode ✓"
    datetime.fromisoformat(agent_event["created_at"])


def test_export_of_db_missing_a_newer_table_still_lists_it_empty(tmp_path):
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE topic (id INTEGER PRIMARY KEY, title VARCHAR NOT NULL)")
    conn.execute("INSERT INTO topic (title) VALUES ('Old')")
    conn.commit()
    conn.close()

    doc = _export(f"sqlite:///{path}", tmp_path / "old.json")

    assert doc["schema_revision"] is None
    assert doc["tables"]["topic"] == [{"id": 1, "title": "Old"}]
    assert doc["tables"]["concept"] == []


# --- restore ------------------------------------------------------------------------------


def _make_db(path: Path, title: str) -> None:
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE topic (id INTEGER PRIMARY KEY, title VARCHAR NOT NULL)")
    conn.execute("INSERT INTO topic (title) VALUES (?)", (title,))
    conn.commit()
    conn.close()


def _titles(path: Path) -> list[str]:
    conn = sqlite3.connect(path)
    try:
        return [r[0] for r in conn.execute("SELECT title FROM topic")]
    finally:
        conn.close()


def test_restore_into_empty_target(tmp_path):
    source = tmp_path / "snap.db"
    _make_db(source, "Restored")
    target = tmp_path / "data" / "adaptive_academy.db"
    target.parent.mkdir()

    pre = backup.restore(source, database_url=f"sqlite:///{target}", backup_dir=tmp_path / "bk")

    assert pre is None
    assert _titles(target) == ["Restored"]


def test_restore_refuses_existing_target_without_force(tmp_path):
    source = tmp_path / "snap.db"
    _make_db(source, "Restored")
    target = tmp_path / "live.db"
    _make_db(target, "Current")

    with pytest.raises(backup.BackupError, match="--force"):
        backup.restore(source, database_url=f"sqlite:///{target}", backup_dir=tmp_path / "bk")
    assert _titles(target) == ["Current"]


def test_restore_with_force_backs_up_current_db_first(tmp_path):
    source = tmp_path / "snap.db"
    _make_db(source, "Restored")
    target = tmp_path / "live.db"
    _make_db(target, "Current")

    pre = backup.restore(
        source, database_url=f"sqlite:///{target}", force=True, backup_dir=tmp_path / "bk"
    )

    assert _titles(target) == ["Restored"]
    assert pre is not None and pre.parent == tmp_path / "bk"
    assert "pre-restore" in pre.name
    assert _titles(pre) == ["Current"]


def test_restore_rejects_a_non_sqlite_file(tmp_path):
    source = tmp_path / "notes.db"
    source.write_text("not a database")
    target = tmp_path / "live.db"
    with pytest.raises(backup.BackupError, match="not a SQLite"):
        backup.restore(source, database_url=f"sqlite:///{target}", backup_dir=tmp_path / "bk")
    assert not target.exists()


def test_restore_rejects_restoring_the_db_onto_itself(tmp_path):
    target = tmp_path / "live.db"
    _make_db(target, "Current")
    with pytest.raises(backup.BackupError, match="itself"):
        backup.restore(
            target, database_url=f"sqlite:///{target}", force=True, backup_dir=tmp_path / "bk"
        )


# --- CLI ----------------------------------------------------------------------------------


def _run_cli(monkeypatch, *argv: str) -> None:
    monkeypatch.setattr("sys.argv", ["aa", *argv])
    cli.main()


def test_cli_backup_default_path(live_db, tmp_path, monkeypatch, capsys):
    _, url = live_db
    monkeypatch.setattr(backup.settings, "database_url", url)
    monkeypatch.chdir(tmp_path)

    _run_cli(monkeypatch, "backup")

    [made] = list((tmp_path / "backups").iterdir())
    assert made.name.startswith("adaptive_academy-") and made.suffix == ".db"
    assert str(made.resolve()) in capsys.readouterr().out
    assert _titles(made) == ["Linear algebra"]


def test_cli_backup_explicit_file_and_directory(live_db, tmp_path, monkeypatch):
    _, url = live_db
    monkeypatch.setattr(backup.settings, "database_url", url)

    _run_cli(monkeypatch, "backup", str(tmp_path / "mine.db"))
    assert _titles(tmp_path / "mine.db") == ["Linear algebra"]

    (tmp_path / "dir").mkdir()
    _run_cli(monkeypatch, "backup", str(tmp_path / "dir"))
    [made] = list((tmp_path / "dir").iterdir())
    assert made.suffix == ".db"


def test_cli_export_writes_json(live_db, tmp_path, monkeypatch, capsys):
    _, url = live_db
    monkeypatch.setattr(backup.settings, "database_url", url)
    monkeypatch.chdir(tmp_path)

    _run_cli(monkeypatch, "export")

    [made] = list((tmp_path / "backups").iterdir())
    assert made.suffix == ".json"
    assert str(made.resolve()) in capsys.readouterr().out
    assert json.loads(made.read_text())["format"] == "adaptive-academy-export"


def test_cli_errors_exit_nonzero_with_message(tmp_path, monkeypatch):
    monkeypatch.setattr(backup.settings, "database_url", "postgresql://localhost/aa")
    with pytest.raises(SystemExit) as exc:
        _run_cli(monkeypatch, "backup", str(tmp_path / "x.db"))
    assert "SQLite" in str(exc.value.code)


def test_cli_restore_requires_force_for_existing_db(tmp_path, monkeypatch):
    source = tmp_path / "snap.db"
    _make_db(source, "Restored")
    target = tmp_path / "live.db"
    _make_db(target, "Current")
    monkeypatch.setattr(backup.settings, "database_url", f"sqlite:///{target}")
    monkeypatch.chdir(tmp_path)

    with pytest.raises(SystemExit):
        _run_cli(monkeypatch, "restore", str(source))
    assert _titles(target) == ["Current"]

    _run_cli(monkeypatch, "restore", str(source), "--force")
    assert _titles(target) == ["Restored"]
    assert any("pre-restore" in p.name for p in (tmp_path / "backups").iterdir())


def test_cli_usage_lists_new_commands(monkeypatch, capsys):
    _run_cli(monkeypatch, "help")
    out = capsys.readouterr().out
    for word in ("backup", "export", "restore"):
        assert word in out
