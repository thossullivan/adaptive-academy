import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "a7d3c5e9f2b1"
PROMPT_TAG_REVISION = "b4e8d2f6a3c9"


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


def _fk_violations(connection) -> list:
    return connection.execute(text("PRAGMA foreign_key_check")).fetchall()


def test_prompt_tag_migration_upgrades_populated_database_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'populated.db'}"
    prior = _alembic(url, "upgrade", PRIOR_REVISION)
    assert prior.returncode == 0, prior.stderr

    # A populated, FK-referenced assessment table (a baseline row referenced by a later one):
    # the column must be added in place, never by recreating the table.
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text("INSERT INTO topic (id, title, created_at, is_demo) "
                 "VALUES (1, 'T', '2026-10-01', 0)"))
        connection.execute(text("INSERT INTO track (id, topic_id, title, overview) "
                                "VALUES (1, 1, 'Core', '')"))
        connection.execute(text(
            "INSERT INTO concept (id, track_id, name, is_load_bearing) VALUES (1, 1, 'C', 1)"))
        connection.execute(text(
            "INSERT INTO assessment (id, concept_id, kind, prompt, response, verdict, score, "
            "gaps, created_at) VALUES (1, 1, 'self_explanation', 'p', 'r', 'v', 0.5, '[]', "
            "'2026-10-01')"))
        connection.execute(text(
            "INSERT INTO assessment (id, concept_id, kind, prompt, response, verdict, score, "
            "gaps, baseline_assessment_id, delta, created_at) VALUES (2, 1, 'calibration', "
            "'p', 'r', 'v', 0.7, '[]', 1, 0.2, '2026-10-02')"))
    engine.dispose()

    upgraded = _alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(url)
    columns = {c["name"]: c for c in inspect(engine).get_columns("assessment")}
    assert "prompt_tag" in columns
    assert columns["prompt_tag"]["nullable"] is True
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == PROMPT_TAG_REVISION
        # Existing rows survived, keep their links, and are NOT backfilled with a guess.
        rows = connection.execute(text(
            "SELECT id, baseline_assessment_id, prompt_tag FROM assessment ORDER BY id"
        )).fetchall()
        assert [tuple(r) for r in rows] == [(1, None, None), (2, 1, None)]
        assert _fk_violations(connection) == []
        connection.execute(text(
            "INSERT INTO assessment (id, concept_id, kind, prompt, response, verdict, score, "
            "gaps, prompt_tag, created_at) VALUES (3, 1, 'teach', 'p', 'r', 'v', 0.6, '[]', "
            "'teach.grade@v2', '2026-10-03')"))
    engine.dispose()

    downgraded = _alembic(url, "downgrade", PRIOR_REVISION)
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(url)
    assert "prompt_tag" not in {c["name"] for c in inspect(engine).get_columns("assessment")}
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        assert connection.execute(text("SELECT count(*) FROM assessment")).scalar() == 3
        assert _fk_violations(connection) == []
    engine.dispose()

    # And back up again: the round trip is repeatable.
    again = _alembic(url, "upgrade", "head")
    assert again.returncode == 0, again.stderr
