import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "c9a7b3e1f204"
USAGE_REVISION = "e5b2a9c4d7f1"


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


def test_usage_migration_upgrades_populated_database_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'populated.db'}"
    prior = _alembic(url, "upgrade", PRIOR_REVISION)
    assert prior.returncode == 0, prior.stderr

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text("INSERT INTO topic (id, title, created_at) VALUES (1, 'T', '2026-10-01')")
        )
    engine.dispose()

    upgraded = _alembic(url, "upgrade", USAGE_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(url)
    inspector = inspect(engine)
    assert "llmusage" in inspector.get_table_names()
    columns = {c["name"]: c for c in inspector.get_columns("llmusage")}
    assert {
        "id", "created_at", "backend", "model", "role", "operation", "feature",
        "input_tokens", "output_tokens", "cache_creation_input_tokens",
        "cache_read_input_tokens", "web_search_requests", "cost_usd",
    } == set(columns)
    assert columns["cost_usd"]["nullable"] is True
    assert columns["feature"]["nullable"] is True
    assert {"ix_llmusage_created_at"} <= {i["name"] for i in inspector.get_indexes("llmusage")}
    with engine.begin() as connection:
        # Existing rows survive; a usage row with an unknown price inserts fine.
        assert connection.execute(text("SELECT count(*) FROM topic")).scalar() == 1
        connection.execute(text(
            "INSERT INTO llmusage (created_at, backend, model, role, operation, "
            "input_tokens, output_tokens, cache_creation_input_tokens, "
            "cache_read_input_tokens, web_search_requests) "
            "VALUES ('2026-10-19', 'anthropic', 'm', 'reasoning', 'complete', 1, 2, 0, 0, 0)"
        ))
    engine.dispose()

    downgraded = _alembic(url, "downgrade", PRIOR_REVISION)
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(url)
    assert "llmusage" not in inspect(engine).get_table_names()
    engine.dispose()
