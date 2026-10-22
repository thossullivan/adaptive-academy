import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "d6a1c3e5f7b9"
ATTEMPT_REVISION = "e7c4a2b9d1f3"


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


def test_attempt_migration_upgrades_populated_database_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'populated.db'}"
    prior = _alembic(url, "upgrade", PRIOR_REVISION)
    assert prior.returncode == 0, prior.stderr

    # A populated conversation with messages: message is FK-referenced by the new table, so
    # its column must be added in place, never by recreating the table.
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
                                "created_at) VALUES (1, 1, 'user', 'my attempt', '2026-10-22')"))
        connection.execute(text("INSERT INTO message (id, conversation_id, role, content, "
                                "created_at) VALUES (2, 1, 'tutor', 'good', '2026-10-22')"))
    engine.dispose()

    upgraded = _alembic(url, "upgrade", ATTEMPT_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(url)
    inspector = inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("message")}
    assert columns["is_attempt"]["nullable"] is True
    attempt_columns = {c["name"] for c in inspector.get_columns("attempt")}
    assert attempt_columns == {"id", "conversation_id", "concept_id", "message_id", "accepted",
                               "created_at"}
    referred = {fk["referred_table"] for fk in inspector.get_foreign_keys("attempt")}
    assert referred == {"conversation", "concept", "message"}
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == ATTEMPT_REVISION
        # Old messages survive, and none is marked as an attempt after the fact.
        assert connection.execute(text("SELECT id, is_attempt FROM message ORDER BY id")
                                  ).fetchall() == [(1, None), (2, None)]
        connection.execute(text("INSERT INTO attempt (conversation_id, concept_id, message_id, "
                                "accepted, created_at) VALUES (1, 1, 1, 1, '2026-10-23')"))
        assert connection.execute(text("PRAGMA foreign_key_check")).fetchall() == []
    engine.dispose()

    downgraded = _alembic(url, "downgrade", PRIOR_REVISION)
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(url)
    inspector = inspect(engine)
    assert "attempt" not in inspector.get_table_names()
    assert "is_attempt" not in {c["name"] for c in inspector.get_columns("message")}
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM message")).scalar() == 2
    engine.dispose()

    again = _alembic(url, "upgrade", "head")
    assert again.returncode == 0, again.stderr
