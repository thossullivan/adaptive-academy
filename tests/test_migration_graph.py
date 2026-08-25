import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "ba15f4c29e71"
GRAPH_TABLES = {"conceptedge", "chunkconcept", "topicsuggestion"}


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
            text("INSERT INTO topic (id, title, created_at) VALUES (1, 'Graph', :now)"),
            {"now": now},
        )
        connection.execute(
            text(
                "INSERT INTO track (id, topic_id, title, overview) "
                "VALUES (1, 1, 'Graph', '')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO concept (id, track_id, name, is_load_bearing) "
                "VALUES (1, 1, 'Attention', 1)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO chunk "
                "(id, kind, source_ref, ordinal, heading, text, context, content_hash, "
                "meta, created_at) VALUES "
                "(1, 'source_doc', 'sourcedoc:1', 0, '', 'Attention', '', :hash, "
                "'{}', :now)"
            ),
            {"hash": "a" * 64, "now": now},
        )
    engine.dispose()


def test_graph_migration_upgrades_populated_database_and_downgrades(tmp_path):
    db_path = tmp_path / "populated.db"
    url = f"sqlite:///{db_path}"

    prior = _alembic(url, "upgrade", PRIOR_REVISION)
    assert prior.returncode == 0, prior.stderr
    _seed_populated_database(url)

    upgraded = _alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr

    engine = create_engine(url)
    inspector = inspect(engine)
    assert GRAPH_TABLES <= set(inspector.get_table_names())
    assert {
        "ix_conceptedge_src_concept_id_valid_until",
        "ix_conceptedge_dst_concept_id_valid_until",
    } == {index["name"] for index in inspector.get_indexes("conceptedge")}
    assert {"ix_topicsuggestion_status_program_id"} == {
        index["name"] for index in inspector.get_indexes("topicsuggestion")
    }
    assert {"uq_chunkconcept_chunk_id_concept_id"} == {
        constraint["name"]
        for constraint in inspector.get_unique_constraints("chunkconcept")
    }
    edge_foreign_keys = {
        tuple(foreign_key["constrained_columns"])
        for foreign_key in inspector.get_foreign_keys("conceptedge")
    }
    assert edge_foreign_keys == {("src_concept_id",), ("dst_concept_id",)}
    engine.dispose()

    downgraded = _alembic(url, "downgrade", "-1")
    assert downgraded.returncode == 0, downgraded.stderr

    engine = create_engine(url)
    inspector = inspect(engine)
    assert GRAPH_TABLES.isdisjoint(inspector.get_table_names())
    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM chunk")).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM concept")).scalar_one() == 1
    engine.dispose()
