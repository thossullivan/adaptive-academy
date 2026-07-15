import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

REPO = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "af45456b0fc5"


def _alembic(url: str, *args: str) -> subprocess.CompletedProcess:
    env = {**os.environ, "AA_DATABASE_URL": url}
    return subprocess.run([sys.executable, "-m", "alembic", *args],
                          cwd=REPO, capture_output=True, text=True, env=env)


def test_migration_applies_on_populated_db(tmp_path):
    db = tmp_path / "seed.db"
    url = f"sqlite:///{db}"
    up_to_prior = _alembic(url, "upgrade", PRIOR_REVISION)
    assert up_to_prior.returncode == 0, up_to_prior.stderr

    eng = create_engine(url)
    with eng.begin() as c:
        now = "2026-07-15 00:00:00"
        c.execute(text(
            "INSERT INTO program (id, title, goal_statement, status, created_at, updated_at)"
            " VALUES (1, 'P', 'g', 'active', :n, :n)"), {"n": now})
        c.execute(text(
            "INSERT INTO milestone (id, program_id, title, success_criteria, order_index,"
            " gate_status, depends_on, override_reason, created_at)"
            " VALUES (1, 1, 'M', '', 0, 'open', '[]', '', :n)"), {"n": now})

    r = _alembic(url, "upgrade", "head")
    assert r.returncode == 0, r.stderr

    with eng.begin() as c:
        cols = [row[1] for row in c.execute(text("PRAGMA table_info(assessment)"))]
        assert "paper_probe_id" in cols
        ev_cols = [row[1] for row in c.execute(text("PRAGMA table_info(agentevent)"))]
        assert "paper_probe_id" in ev_cols
        names = [row[0] for row in c.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'"))]
        assert "paperprobe" in names and "paperprobeanswer" in names
