import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "b4e8d2f6a3c9"
REPORTED_COST_REVISION = "c8e1f4a7b2d6"


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


def _insert_usage(connection, row_id: int, backend: str, cost: str) -> None:
    connection.execute(text(
        "INSERT INTO llmusage (id, created_at, backend, model, role, operation, input_tokens, "
        "output_tokens, cache_creation_input_tokens, cache_read_input_tokens, "
        f"web_search_requests, cost_usd) VALUES ({row_id}, '2026-10-21', '{backend}', "
        f"'claude-sonnet-5-5', 'reasoning', 'complete', 10, 5, 0, 0, 0, {cost})"))


def test_reported_cost_migration_upgrades_populated_database_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'populated.db'}"
    prior = _alembic(url, "upgrade", PRIOR_REVISION)
    assert prior.returncode == 0, prior.stderr

    engine = create_engine(url)
    with engine.begin() as connection:
        _insert_usage(connection, 1, "anthropic", "0.0012")
        _insert_usage(connection, 2, "anthropic", "NULL")  # an unpriced model
    engine.dispose()

    upgraded = _alembic(url, "upgrade", "head")
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(url)
    inspector = inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("llmusage")}
    assert "reported_cost_usd" in columns
    assert columns["reported_cost_usd"]["nullable"] is True
    # Added in place: the table and its index were not recreated.
    assert {"ix_llmusage_created_at"} <= {i["name"] for i in inspector.get_indexes("llmusage")}
    with engine.begin() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == REPORTED_COST_REVISION
        # Existing rows survive with their list-price cost, and no reported cost is invented.
        rows = connection.execute(text(
            "SELECT id, cost_usd, reported_cost_usd FROM llmusage ORDER BY id")).fetchall()
        assert [tuple(r) for r in rows] == [(1, 0.0012, None), (2, None, None)]
        connection.execute(text(
            "INSERT INTO llmusage (created_at, backend, model, role, operation, input_tokens, "
            "output_tokens, cache_creation_input_tokens, cache_read_input_tokens, "
            "web_search_requests, cost_usd, reported_cost_usd) VALUES ('2026-10-22', "
            "'openrouter', 'deepseek/deepseek-v4', 'reasoning', 'complete', 10, 5, 0, 0, 0, "
            "NULL, 0.0007)"))
    engine.dispose()

    downgraded = _alembic(url, "downgrade", PRIOR_REVISION)
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(url)
    assert "reported_cost_usd" not in {c["name"] for c in inspect(engine).get_columns("llmusage")}
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM llmusage")).scalar() == 3
    engine.dispose()

    again = _alembic(url, "upgrade", "head")
    assert again.returncode == 0, again.stderr
