"""Point every path-like app setting at a throwaway directory before the app is imported.

`just test` loads the developer's .env into the environment (justfile: dotenv-load), and
Settings (settings.py) also reads ./.env on its own. Either would hand the test process the
developer's real AA_DATABASE_URL, vault, embedding cache and frontend build. `settings` is
created when adaptive_academy.settings is first imported, and `db.engine` is built from it
right then, so this module must run before any adaptive_academy import: tests/conftest.py
imports it first. Environment variables take precedence over .env in pydantic-settings, so
the values below win over both sources, whatever the developer's shell or .env says.

Every path from the tests to a database goes through `settings.database_url`: db.engine
(used by api/deps.get_session and the retriever's ensure_fts/ensure_vec, the startup hook's
create_db_and_tables, the CLI and seed defaults, the usage recorder's default bind, and
alembic/env.py), and engine/backup.py (snapshot, export, restore default to it). The SQLite
guard in conftest.py backs this up at runtime: any connection to a database file outside the
temp directory fails the test that opened it.
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

if any(name == "adaptive_academy" or name.startswith("adaptive_academy.")
       for name in sys.modules):  # pragma: no cover - a guard on import order
    raise RuntimeError(
        "adaptive_academy was imported before tests/_isolated_env.py ran, so its settings "
        "(and the database engine) may already point at the developer's real files. Import "
        "_isolated_env first in tests/conftest.py."
    )

# One directory per test session; removed when the process exits.
TEST_DATA_DIR = Path(tempfile.mkdtemp(prefix="aa-tests-")).resolve()
TEST_DATABASE = TEST_DATA_DIR / "adaptive_academy.db"
EMBEDDING_CACHE = TEST_DATA_DIR / "fastembed_cache"

ISOLATED_ENV = {
    # settings.database_url: db.engine, engine/backup.py, alembic/env.py, usage recording.
    "AA_DATABASE_URL": f"sqlite:///{TEST_DATABASE}",
    # settings.obsidian_vault_path: the vault routes' default read/write target. Blank is
    # "no default vault", the same as an install without the setting.
    "AA_OBSIDIAN_VAULT_PATH": "",
    # settings.embedding_cache_dir (OnnxEmbedder) and fastembed's own fallback location.
    "AA_EMBEDDING_CACHE_DIR": str(EMBEDDING_CACHE),
    "FASTEMBED_CACHE_PATH": str(EMBEDDING_CACHE),
    # settings.frontend_dist: read-only, but pinned so a local build never changes routing.
    "AA_FRONTEND_DIST": str(TEST_DATA_DIR / "frontend_build"),
}
os.environ.update(ISOLATED_ENV)
atexit.register(shutil.rmtree, TEST_DATA_DIR, ignore_errors=True)
