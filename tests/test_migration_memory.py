import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "d3b9f1c274ae"
MEMORY_OBJECTS = {
    "chunk",
    "vaultlink",
    "chunk_fts",
    "chunk_ai",
    "chunk_ad",
    "chunk_au",
}


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


def _seed_populated_database(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        now = "2026-08-25 00:00:00"
        connection.execute(
            text(
                "INSERT INTO topic (id, title, created_at) "
                "VALUES (1, 'Memory', :now)"
            ),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO track (id, topic_id, title, overview) "
                "VALUES (1, 1, 'Retrieval', '')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO concept (id, track_id, name, is_load_bearing) "
                "VALUES (1, 1, 'FTS5', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO assessment "
                "(id, concept_id, kind, prompt, response, verdict, score, created_at) "
                "VALUES (1, 1, 'self_explanation', 'Explain FTS5', "
                "'It is a full-text index.', 'pass', 0.9, :now)"
            ),
            {"now": now},
        )
    engine.dispose()


def _schema_objects(url: str) -> set[str]:
    engine = create_engine(url)
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT name FROM sqlite_master "
                "WHERE type IN ('table', 'trigger')"
            )
        )
        names = {row[0] for row in rows}
    engine.dispose()
    return names


def test_memory_migration_upgrades_populated_database_and_downgrades(tmp_path):
    db_path = tmp_path / "populated.db"
    url = f"sqlite:///{db_path}"

    prior = _alembic(url, "upgrade", PRIOR_REVISION)
    assert prior.returncode == 0, prior.stderr
    _seed_populated_database(url)

    upgraded = _alembic(url, "upgrade", "ba15f4c29e71")  # the memory-chunks revision; downgrade -1 must drop it
    assert upgraded.returncode == 0, upgraded.stderr
    assert MEMORY_OBJECTS <= _schema_objects(url)

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("PRAGMA foreign_keys=ON"))
        connection.execute(
            text(
                "INSERT INTO chunk "
                "(kind, source_ref, ordinal, heading, text, context, content_hash, "
                "meta, created_at) "
                "VALUES ('source_doc', 'sourcedoc:1', 0, 'Sec', 'hello', "
                "'Doc > Sec', :hash, '{}', :now)"
            ),
            {"hash": "d" * 64, "now": "2026-08-25 00:00:00"},
        )
        hello = connection.execute(
            text("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH 'hello'")
        ).all()
        section = connection.execute(
            text("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH 'sec'")
        ).all()
        assessment_count = connection.execute(
            text("SELECT count(*) FROM assessment")
        ).scalar_one()
    engine.dispose()

    assert len(hello) == 1
    assert len(section) == 1
    assert assessment_count == 1

    downgraded = _alembic(url, "downgrade", "-1")
    assert downgraded.returncode == 0, downgraded.stderr
    assert MEMORY_OBJECTS.isdisjoint(_schema_objects(url))
