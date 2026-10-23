import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "e7c4a2b9d1f3"
NOTE_REVISION = "f2b8d4a6c1e3"


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, "AA_DATABASE_URL": url}
    return subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_concept_note_migration_upgrades_populated_database_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'populated.db'}"
    prior = _alembic(url, "upgrade", PRIOR_REVISION)
    assert prior.returncode == 0, prior.stderr

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(text("INSERT INTO topic (id, title, created_at, is_demo) "
                                "VALUES (1, 'T', '2026-10-22', 0)"))
        connection.execute(text("INSERT INTO track (id, topic_id, title, overview) "
                                "VALUES (1, 1, 'Core', '')"))
        connection.execute(text("INSERT INTO concept (id, track_id, name, is_load_bearing) "
                                "VALUES (1, 1, 'softmax', 0)"))
        connection.execute(text("INSERT INTO conversation (id, topic_id, concept_id, "
                                "attempt_logged, created_at) VALUES (1, 1, 1, 1, '2026-10-22')"))
        connection.execute(text("INSERT INTO message (id, conversation_id, role, content, "
                                "is_attempt, created_at) VALUES (1, 1, 'user', 'try', 1, "
                                "'2026-10-22')"))
        connection.execute(text("INSERT INTO message (id, conversation_id, role, content, "
                                "created_at) VALUES (2, 1, 'tutor', 'solved', '2026-10-22')"))
        connection.execute(text("INSERT INTO attempt (conversation_id, concept_id, message_id, "
                                "accepted, created_at) VALUES (1, 1, 1, 1, '2026-10-22')"))
    engine.dispose()

    upgraded = _alembic(url, "upgrade", NOTE_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(url)
    inspector = inspect(engine)
    note_columns = {c["name"]: c for c in inspector.get_columns("concept_note")}
    assert set(note_columns) == {"id", "concept_id", "body", "updated_at"}
    assert note_columns["body"]["nullable"] is False
    assert {fk["referred_table"] for fk in inspector.get_foreign_keys("concept_note")} == {
        "concept"}
    unique = inspector.get_unique_constraints("concept_note")
    assert [u["column_names"] for u in unique] == [["concept_id"]]
    assert inspector.get_columns("message")[-1]["name"] == "reveals_solution"
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar() == (
            NOTE_REVISION)
        # Old messages survive; none is marked as a revealed solution after the fact.
        assert connection.execute(text("SELECT id, is_attempt, reveals_solution FROM message "
                                       "ORDER BY id")).fetchall() == [(1, 1, None), (2, None, None)]
        assert connection.execute(text("SELECT count(*) FROM attempt")).scalar() == 1
        connection.execute(text("INSERT INTO concept_note (concept_id, body, updated_at) "
                                "VALUES (1, 'mine', '2026-10-23')"))
        assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    engine.dispose()

    downgraded = _alembic(url, "downgrade", PRIOR_REVISION)
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(url)
    inspector = inspect(engine)
    assert "concept_note" not in inspector.get_table_names()
    assert "reveals_solution" not in {c["name"] for c in inspector.get_columns("message")}
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM message")).scalar() == 2
        assert connection.execute(text("SELECT count(*) FROM attempt")).scalar() == 1
    engine.dispose()

    again = _alembic(url, "upgrade", "head")
    assert again.returncode == 0, again.stderr
