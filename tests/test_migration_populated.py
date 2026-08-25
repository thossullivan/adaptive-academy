"""Regression guard: the map-revision migration must apply to a POPULATED database.

The in-memory suite runs migrations against empty tables, so it never exercised
SQLite batch-mode table recreation dropping a `milestone` table that live
`programtopiclink` rows reference under `PRAGMA foreign_keys=ON`. That combination
(the real volume db: 6 milestones, 18 links) failed in production with
`FOREIGN KEY constraint failed`. This test seeds the referencing rows at the prior
revision, then upgrades to head — reproducing the exact prod condition.
"""

import subprocess
import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "5e252d8109c0"  # program-layer head, before map-revision


def _alembic(db_url: str, *args: str) -> subprocess.CompletedProcess:
    environment = {
        "PATH": os.environ["PATH"],
        "AA_DATABASE_URL": db_url,
    }
    if cache_dir := os.environ.get("UV_CACHE_DIR"):
        environment["UV_CACHE_DIR"] = cache_dir
    return subprocess.run(
        ["uv", "run", "--offline", "alembic", *args],
        cwd=REPO_ROOT,
        env=environment,
        capture_output=True,
        text=True,
    )


def _seed_referencing_rows(db_path: Path) -> None:
    """Insert program -> milestone -> programtopiclink so the child rows reference
    a milestone (the exact FK edge that batch recreation trips)."""
    import sqlite3

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys=ON")
    now = "2026-07-10 00:00:00"
    conn.execute(
        "INSERT INTO program (id, title, goal_statement, status, created_at, updated_at)"
        " VALUES (1, 'P', 'g', 'active', ?, ?)", (now, now))
    conn.execute(
        "INSERT INTO milestone (id, program_id, title, success_criteria, order_index,"
        " gate_status, depends_on, override_reason, created_at)"
        " VALUES (1, 1, 'M', '', 0, 'open', '[]', '', ?)", (now,))
    conn.execute(
        "INSERT INTO programtopiclink (id, milestone_id, topic_id, status,"
        " proposed_title, why, sources, created_at)"
        " VALUES (1, 1, NULL, 'stub', 'T', '', '[]', ?)", (now,))
    conn.commit()
    conn.close()


def test_migration_applies_to_populated_referenced_tables(tmp_path):
    db_path = tmp_path / "populated.db"
    db_url = f"sqlite:///{db_path}"

    up_to_prior = _alembic(db_url, "upgrade", PRIOR_REVISION)
    assert up_to_prior.returncode == 0, up_to_prior.stderr

    _seed_referencing_rows(db_path)

    to_head = _alembic(db_url, "upgrade", "head")
    assert to_head.returncode == 0, (
        "migration failed on a populated db (the prod condition):\n" + to_head.stderr
    )

    import sqlite3

    conn = sqlite3.connect(db_path)
    milestone_cols = {r[1] for r in conn.execute("PRAGMA table_info(milestone)")}
    link_cols = {r[1] for r in conn.execute("PRAGMA table_info(programtopiclink)")}
    version = conn.execute("SELECT version_num FROM alembic_version").fetchone()[0]
    # the seeded rows survived the migration
    milestone_count = conn.execute("SELECT count(*) FROM milestone").fetchone()[0]
    link_count = conn.execute("SELECT count(*) FROM programtopiclink").fetchone()[0]
    conn.close()

    assert "archived" in milestone_cols
    assert "added_by" in link_cols
    assert version == "ba15f4c29e71"  # head as of the memory-chunks migration
    assert milestone_count == 1 and link_count == 1
