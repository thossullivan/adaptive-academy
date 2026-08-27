import os
import struct
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from adaptive_academy.db import ensure_vec

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


def test_memory_migration_downgrade_upgrade_clears_chunk_vectors(tmp_path):
    pytest.importorskip("sqlite_vec")
    db_path = tmp_path / "vectors.db"
    url = f"sqlite:///{db_path}"

    upgraded = _alembic(url, "upgrade", "ba15f4c29e71")
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(url)
    assert ensure_vec(engine) is True
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO chunk "
                "(id, kind, source_ref, ordinal, heading, text, context, content_hash, "
                "meta, created_at) VALUES "
                "(1, 'source_doc', 'sourcedoc:1', 0, '', 'stale', '', :hash, '{}', :now)"
            ),
            {"hash": "e" * 64, "now": "2026-08-25 00:00:00"},
        )
        connection.execute(
            text(
                "INSERT INTO chunk_vec(chunk_id, embedding) "
                "VALUES (1, :embedding)"
            ),
            {"embedding": struct.pack("<384f", *([0.0] * 384))},
        )
        assert connection.execute(text("SELECT count(*) FROM chunk_vec")).scalar_one() == 1
    engine.dispose()

    downgraded = _alembic(url, "downgrade", "-1")
    assert downgraded.returncode == 0, downgraded.stderr
    assert "chunk_vec" not in _schema_objects(url)

    reupgraded = _alembic(url, "upgrade", "ba15f4c29e71")
    assert reupgraded.returncode == 0, reupgraded.stderr
    engine = create_engine(url)
    assert ensure_vec(engine) is True
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM chunk_vec")).scalar_one() == 0
    engine.dispose()


def test_memory_migration_skips_fts_ddl_when_fts5_is_missing():
    import importlib.util
    from pathlib import Path

    from sqlalchemy.exc import OperationalError

    spec = importlib.util.spec_from_file_location(
        "mig_memory", Path("alembic/versions/ba15f4c29e71_memory_chunks.py")
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    executed: list[str] = []

    def no_fts5(statement: str) -> None:
        executed.append(statement)
        raise OperationalError(statement, {}, RuntimeError("no such module: fts5"))

    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        assert module._apply_fts_ddl(no_fts5) is False
    assert executed and "fts5" in executed[0]
    assert any("FTS5 unavailable" in str(w.message) for w in caught)
