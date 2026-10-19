import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "e5b2a9c4d7f1"
DEMO_REVISION = "a7d3c5e9f2b1"


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


def test_demo_flag_migration_upgrades_populated_database_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'populated.db'}"
    prior = _alembic(url, "upgrade", PRIOR_REVISION)
    assert prior.returncode == 0, prior.stderr

    # A populated, FK-referenced topic table: the column must be added in place, never by
    # recreating the table (which breaks the foreign keys pointing at it).
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text("INSERT INTO topic (id, title, created_at) VALUES (1, 'T', '2026-10-01')")
        )
        connection.execute(text("INSERT INTO track (id, topic_id, title, overview) "
                                "VALUES (1, 1, 'Core', '')"))
    engine.dispose()

    upgraded = _alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(url)
    columns = {c["name"]: c for c in inspect(engine).get_columns("topic")}
    assert "is_demo" in columns
    assert columns["is_demo"]["nullable"] is False
    with engine.begin() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == DEMO_REVISION
        # The existing topic survived, is not a demo, and still owns its track.
        assert connection.execute(text("SELECT is_demo FROM topic WHERE id = 1")).scalar() == 0
        assert connection.execute(text("SELECT count(*) FROM track")).scalar() == 1
        connection.execute(text("INSERT INTO topic (title, created_at, is_demo) "
                                "VALUES ('Demo', '2026-10-02', 1)"))
    engine.dispose()

    downgraded = _alembic(url, "downgrade", PRIOR_REVISION)
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(url)
    assert "is_demo" not in {c["name"] for c in inspect(engine).get_columns("topic")}
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM topic")).scalar() == 2
    engine.dispose()
