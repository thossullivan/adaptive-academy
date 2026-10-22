"""The suite can never touch the developer's real database (or vault, or caches).

`just test` loads .env into the environment and Settings reads ./.env itself, so a real
AA_DATABASE_URL would reach `settings` and the engine built from it at import time. The
tests/_isolated_env.py module (imported first by conftest.py) points every path-like setting
at a per-session temp directory, and the SQLite guard in conftest.py blocks any connection to
a database file outside the temp directory. These tests fail if either stops holding.
"""

import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from _isolated_env import ISOLATED_ENV, TEST_DATA_DIR
from adaptive_academy import db
from adaptive_academy.api import deps
from adaptive_academy.engine import backup
from adaptive_academy.llm import usage
from adaptive_academy.settings import Settings, settings
from conftest import _DB_GUARD, RealDatabaseBlockedError

REPO_ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home().resolve()
TEMP = Path(tempfile.gettempdir()).resolve()

# Every Settings field, sorted into "names a file or directory" or not. A new field fails
# test_every_path_like_setting_is_isolated until it is sorted here (and, if it is a path,
# pinned in _isolated_env.ISOLATED_ENV).
PATH_SETTINGS = {"database_url", "embedding_cache_dir", "obsidian_vault_path", "frontend_dist"}
OTHER_SETTINGS = {"retriever", "embedding_model", "embedding_allow_download",
                  "reasoning_model", "copy_model", "daily_budget_usd", "grading_strictness"}


def assert_isolated(path_text: str | None, what: str) -> None:
    assert path_text, f"{what} is empty"
    path = Path(path_text).expanduser().resolve()
    assert path.is_relative_to(TEST_DATA_DIR), f"{what} = {path} is outside {TEST_DATA_DIR}"
    assert not path.is_relative_to(REPO_ROOT), f"{what} = {path} is inside the repo"
    assert path.is_relative_to(TEMP) or not path.is_relative_to(HOME), (
        f"{what} = {path} is in the home directory, outside tmp")


def test_the_session_dir_is_a_fresh_temp_dir():
    assert TEST_DATA_DIR.is_relative_to(TEMP)
    assert TEST_DATA_DIR.name.startswith("aa-tests-")


def test_settings_database_url_is_the_isolated_one():
    assert settings.database_url == ISOLATED_ENV["AA_DATABASE_URL"]
    assert_isolated(make_url(settings.database_url).database, "settings.database_url")


def test_the_app_engine_and_every_user_of_it_point_at_the_temp_dir():
    assert_isolated(db.engine.url.database, "db.engine")
    # api/deps.get_session and the retriever's ensure_fts/ensure_vec use this same engine.
    assert deps.engine is db.engine
    # alembic/env.py migrates through the app engine, so it resolves the same URL.
    assert "from adaptive_academy.db import engine" in (REPO_ROOT / "alembic" / "env.py"
                                                        ).read_text()


def test_usage_recording_defaults_to_the_isolated_engine():
    usage.reset_usage_bind()  # the autouse fixture turns recording off; check the default
    try:
        bind = usage.get_usage_bind()
        assert bind is db.engine
        assert_isolated(bind.url.database, "usage default bind")
    finally:
        usage.set_usage_bind(None)


def test_backup_export_restore_default_to_the_isolated_file():
    assert_isolated(str(backup.sqlite_path()), "backup.sqlite_path()")


def test_path_settings_are_isolated():
    assert_isolated(settings.embedding_cache_dir, "settings.embedding_cache_dir")
    assert_isolated(os.environ["FASTEMBED_CACHE_PATH"], "FASTEMBED_CACHE_PATH")
    assert_isolated(settings.frontend_dist, "settings.frontend_dist")
    assert settings.obsidian_vault_path == ""  # no default vault to write into


def test_every_path_like_setting_is_isolated():
    assert set(Settings.model_fields) == PATH_SETTINGS | OTHER_SETTINGS, (
        "a Settings field was added or renamed: sort it into PATH_SETTINGS or "
        "OTHER_SETTINGS, and pin a path-like one in tests/_isolated_env.py")
    for name in PATH_SETTINGS:
        assert f"AA_{name.upper()}" in ISOLATED_ENV, name


def test_a_fresh_settings_object_ignores_the_developers_env_file(tmp_path, monkeypatch):
    # Settings reads ./.env itself; the environment wins over it.
    (tmp_path / ".env").write_text(
        "AA_DATABASE_URL=sqlite:////should/never/be/used.db\n"
        "AA_OBSIDIAN_VAULT_PATH=/should/never/be/used\n")
    monkeypatch.chdir(tmp_path)
    fresh = Settings()
    assert fresh.database_url == ISOLATED_ENV["AA_DATABASE_URL"]
    assert fresh.obsidian_vault_path == ""


@pytest.mark.parametrize("where", ["repo", "home"])
def test_guard_blocks_a_database_file_outside_tmp(request, where):
    root = REPO_ROOT if where == "repo" else HOME
    target = root / "aa-isolation-guard-probe.db"
    try:
        with pytest.raises(RealDatabaseBlockedError):
            sqlite3.connect(target)
        with pytest.raises(RealDatabaseBlockedError):
            create_engine(f"sqlite:///{target}").connect()
        with pytest.raises(RealDatabaseBlockedError):
            sqlite3.connect(f"file:{target}?mode=ro", uri=True)
        assert not target.exists()
    finally:
        # The attempts were deliberate; consume them so the teardown check passes.
        attempts = _DB_GUARD.attempts.pop(request.node.nodeid, [])
    assert attempts == [str(target.resolve())] * 3


def test_guard_allows_memory_and_temp_databases(tmp_path):
    sqlite3.connect(":memory:").close()
    sqlite3.connect("file::memory:?cache=shared", uri=True).close()
    sqlite3.connect(tmp_path / "ok.db").close()
    create_engine("sqlite://").connect().close()
    assert (tmp_path / "ok.db").exists()


def test_a_sentinel_database_url_in_the_environment_is_never_used(tmp_path):
    """A developer's real settings in the environment (as `just test` exports them) don't
    reach the app: a child pytest run with sentinel paths passes this file's checks and never
    creates the sentinel database."""
    sentinel_db = tmp_path / "sentinel.db"
    env = {**os.environ,
           "AA_DATABASE_URL": f"sqlite:///{sentinel_db}",
           "AA_OBSIDIAN_VAULT_PATH": str(tmp_path / "sentinel-vault"),
           "AA_EMBEDDING_CACHE_DIR": str(tmp_path / "sentinel-cache"),
           "AA_FRONTEND_DIST": str(tmp_path / "sentinel-frontend")}
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         f"{Path(__file__).name}", "-k", "not sentinel"],
        cwd=Path(__file__).parent, env=env, capture_output=True, text=True, timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert " passed" in result.stdout
    assert not sentinel_db.exists()
    assert not (tmp_path / "sentinel-vault").exists()
