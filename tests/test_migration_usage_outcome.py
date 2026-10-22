import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, inspect, text

REPO_ROOT = Path(__file__).resolve().parents[1]
PRIOR_REVISION = "c8e1f4a7b2d6"
OUTCOME_REVISION = "d6a1c3e5f7b9"


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


def test_outcome_migration_upgrades_populated_database_and_downgrades(tmp_path):
    url = f"sqlite:///{tmp_path / 'populated.db'}"
    prior = _alembic(url, "upgrade", PRIOR_REVISION)
    assert prior.returncode == 0, prior.stderr

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("INSERT INTO topic (id, title, created_at, is_demo) "
                                "VALUES (1, 'T', '2026-10-21', 0)"))
        connection.execute(text(
            "INSERT INTO agentevent (id, topic_id, kind, detail, created_at) "
            "VALUES (1, 1, 'grade:check', 'grade attempt=1 pass', '2026-10-21')"))
        connection.execute(text(
            "INSERT INTO llmusage (id, created_at, backend, model, role, operation, "
            "input_tokens, output_tokens, cache_creation_input_tokens, "
            "cache_read_input_tokens, web_search_requests, cost_usd) VALUES (1, "
            "'2026-10-21', 'anthropic', 'claude-sonnet-5-5', 'reasoning', 'complete', 10, 5, "
            "0, 0, 0, 0.001)"))
    engine.dispose()

    upgraded = _alembic(url, "upgrade", OUTCOME_REVISION)
    assert upgraded.returncode == 0, upgraded.stderr
    engine = create_engine(url)
    inspector = inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("llmusage")}
    assert columns["outcome"]["nullable"] is True
    # Added in place: llmusage keeps its index, and agentevent gains one for the scorecard.
    assert "ix_llmusage_created_at" in {i["name"] for i in inspector.get_indexes("llmusage")}
    event_indexes = {i["name"]: i["column_names"] for i in inspector.get_indexes("agentevent")}
    assert event_indexes["ix_agentevent_kind_created_at"] == ["kind", "created_at"]
    with engine.begin() as connection:
        version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
        assert version == OUTCOME_REVISION
        # Old rows survive, and no outcome is invented for them.
        assert connection.execute(text("SELECT outcome FROM llmusage")).fetchall() == [(None,)]
        assert connection.execute(text("SELECT count(*) FROM agentevent")).scalar() == 1
        connection.execute(text(
            "INSERT INTO llmusage (created_at, backend, model, role, operation, input_tokens, "
            "output_tokens, cache_creation_input_tokens, cache_read_input_tokens, "
            "web_search_requests, cost_usd, outcome) VALUES ('2026-10-22', 'anthropic', "
            "'claude-sonnet-5-5', 'reasoning', 'complete_json', 10, 5, 0, 0, 0, 0.001, "
            "'invalid_output')"))
    engine.dispose()

    downgraded = _alembic(url, "downgrade", PRIOR_REVISION)
    assert downgraded.returncode == 0, downgraded.stderr
    engine = create_engine(url)
    inspector = inspect(engine)
    assert "outcome" not in {c["name"] for c in inspector.get_columns("llmusage")}
    assert "ix_agentevent_kind_created_at" not in {
        i["name"] for i in inspector.get_indexes("agentevent")}
    with engine.begin() as connection:
        assert connection.execute(text("SELECT count(*) FROM llmusage")).scalar() == 2
    engine.dispose()

    again = _alembic(url, "upgrade", "head")
    assert again.returncode == 0, again.stderr
