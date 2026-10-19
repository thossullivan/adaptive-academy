"""Back up, export, and restore the learning record — the user owns it and can take it along.

Three operations, all against the SQLite file named by `settings.database_url`:

- `snapshot`: a consistent copy of the live db via SQLite's online backup API. Safe while the
  app runs in WAL mode (the copy is one read transaction, so writers keep going), and the
  result is converted to rollback-journal mode: one self-contained file, no -wal/-shm.
- `export_record`: the whole record as a versioned JSON document (format below), read from a
  private snapshot so every table comes from the same instant.
- `restore`: copy a snapshot back over the live db (backup API in reverse), refusing to replace
  an existing db without `force` and snapshotting it first. Run `alembic upgrade head` after.

Export format (version 1)::

    {"format": "adaptive-academy-export", "version": 1,
     "exported_at": "<ISO 8601, UTC>", "schema_revision": "<alembic revision or null>",
     "encoding": {...}, "excluded_tables": {"<name>": "<why>"},
     "tables": {"<table>": [{"<column>": <value>, ...}, ...], ...}}

Every SQLModel table is listed (iterated from metadata, so new tables are included without
touching this module), rows ordered by primary key. Datetimes are ISO 8601; the app writes UTC
but SQLite keeps no offset, so they come back naive. JSON columns stay structured. Bytes would be
base64 (no current column is binary).
"""

from __future__ import annotations

import base64
import json
import os
import sqlite3
import tempfile
from collections.abc import Iterator
from datetime import date, datetime, time, timezone
from pathlib import Path
from typing import Any, Literal, TextIO

from sqlalchemy import Table, create_engine, inspect, select
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import ArgumentError
from sqlmodel import SQLModel

import adaptive_academy.models  # noqa: F401  (register every table in SQLModel.metadata)
from adaptive_academy.settings import settings

EXPORT_FORMAT = "adaptive-academy-export"
EXPORT_VERSION = 1
SQLITE_BUSY_TIMEOUT_S = 30
_SQLITE_MAGIC = b"SQLite format 3\x00"

# Derived search indexes, left out of the JSON export because they are rebuilt from the
# exported rows (and are binary/engine-specific anyway). Neither is a SQLModel table today, so
# the metadata walk never reaches them; the list documents the decision and guards against a
# future model mapping onto them. Their FTS5/vec0 shadow tables (chunk_fts_data, chunk_vec_*,
# ...) are excluded by prefix. The `chunk` rows themselves ARE exported: they carry fetched
# source and paper text that may not be re-fetchable offline. The snapshot (.db) keeps all of it.
EXCLUDED_TABLES: dict[str, str] = {
    "chunk_fts": "FTS5 keyword index over chunk.context/text; rebuilt by db.ensure_fts",
    "chunk_vec": "sqlite-vec embeddings (float[384]) of chunk text; recomputed by a memory "
    "reindex (POST /api/memory/reindex)",
}


class BackupError(RuntimeError):
    """A backup, export, or restore could not be done; the message is user-facing."""


def sqlite_path(database_url: str | None = None) -> Path:
    """The db file behind a sqlite URL (default: settings). Anything else is a clear error."""
    url_text = database_url if database_url is not None else settings.database_url
    try:
        url = make_url(url_text)
    except ArgumentError as exc:
        raise BackupError(f"cannot parse database URL: {exc}") from exc
    if url.get_backend_name() != "sqlite":
        raise BackupError(
            f"backup/export supports SQLite databases only; AA_DATABASE_URL uses "
            f"'{url.get_backend_name()}'"
        )
    if not url.database or url.database == ":memory:":
        raise BackupError("backup/export needs a file-backed SQLite database, not in-memory")
    return Path(url.database).expanduser().absolute()


def timestamp(now: datetime | None = None) -> str:
    """Local-time stamp for file names, so a backups/ listing reads like the user's clock."""
    return (now or datetime.now()).strftime("%Y%m%d-%H%M%S")


def default_name(kind: Literal["db", "json"], now: datetime | None = None) -> str:
    return f"adaptive_academy-{timestamp(now)}.{kind}"


def _live_db(database_url: str | None) -> Path:
    path = sqlite_path(database_url)
    if not path.is_file():
        # Never let sqlite3.connect create an empty db as a side effect of a backup.
        raise BackupError(f"database {path} does not exist")
    return path


def _claim(dest: Path) -> Path:
    """Validate `dest` and return a sibling temp path; callers os.replace() it into place, so
    a failed or interrupted run never leaves a half-written file under the final name."""
    if dest.exists():
        raise BackupError(f"{dest} already exists; choose another path")
    if not dest.parent.is_dir():
        raise BackupError(f"directory {dest.parent} does not exist")
    fd, partial = tempfile.mkstemp(prefix=f".{dest.name}.", suffix=".partial", dir=dest.parent)
    os.close(fd)
    return Path(partial)


def _copy_db(source: Path, dest: Path) -> None:
    """Online-backup `source` into `dest` and make `dest` a self-contained rollback-journal db."""
    src = sqlite3.connect(source, timeout=SQLITE_BUSY_TIMEOUT_S)
    try:
        dst = sqlite3.connect(dest)
        try:
            src.backup(dst)  # pages=-1: one step, one read transaction -> consistent copy
            # Page 1 came across marked WAL; switch the copy so it needs no -wal/-shm beside it.
            dst.execute("PRAGMA journal_mode=DELETE")
        finally:
            dst.close()
    finally:
        src.close()
    for suffix in ("-wal", "-shm", "-journal"):
        Path(f"{dest}{suffix}").unlink(missing_ok=True)


def snapshot(dest: Path, *, database_url: str | None = None) -> Path:
    """Write a consistent, self-contained copy of the live db to `dest` (must not exist)."""
    source = _live_db(database_url)
    dest = Path(dest)
    partial = _claim(dest)
    try:
        partial.unlink()  # sqlite3 wants to create the file itself
        _copy_db(source, partial)
        os.replace(partial, dest)
    except sqlite3.Error as exc:
        raise BackupError(f"snapshot failed: {exc}") from exc
    finally:
        _cleanup(partial)
    return dest


def _cleanup(path: Path) -> None:
    for suffix in ("", "-wal", "-shm", "-journal"):
        Path(f"{path}{suffix}").unlink(missing_ok=True)


# --- JSON export --------------------------------------------------------------------------


def _is_excluded(name: str) -> bool:
    return any(name == t or name.startswith(f"{t}_") for t in EXCLUDED_TABLES)


def _encode(value: Any) -> Any:
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, bytearray, memoryview)):
        return base64.b64encode(bytes(value)).decode("ascii")
    raise TypeError(f"cannot export value of type {type(value).__name__}")


def _dumps(value: Any) -> str:
    return json.dumps(value, default=_encode, ensure_ascii=False)


def _schema_revision(conn: Connection, present: set[str]) -> str | None:
    if "alembic_version" not in present:
        return None
    versions = sorted(r[0] for r in conn.exec_driver_sql("SELECT version_num FROM alembic_version"))
    return ",".join(versions) or None


def _rows(conn: Connection, table: Table, db_columns: set[str]) -> Iterator[dict[str, Any]]:
    # Only columns the db actually has: an export of a db at an older schema revision still
    # works (the missing columns are simply absent from its rows).
    columns = [c for c in table.columns if c.name in db_columns]
    if not columns:
        return
    order = [c for c in table.primary_key.columns if c.name in db_columns]
    result = conn.execution_options(stream_results=True).execute(
        select(*columns).order_by(*order)
    )
    for row in result.mappings():
        yield dict(row)


def write_export(fp: TextIO, db_file: Path, *, now: datetime | None = None) -> None:
    """Stream the JSON export of the db at `db_file` (a snapshot, not the live db) to `fp`."""
    engine = create_engine(f"sqlite:///{db_file}")
    try:
        with engine.connect() as conn:
            inspector = inspect(conn)
            present = set(inspector.get_table_names())
            header = {
                "format": EXPORT_FORMAT,
                "version": EXPORT_VERSION,
                "exported_at": (now or datetime.now(timezone.utc)).isoformat(),
                "schema_revision": _schema_revision(conn, present),
                "encoding": {
                    "datetime": "ISO 8601 (naive values are UTC)",
                    "bytes": "base64",
                    "json_columns": "inline JSON",
                },
                "excluded_tables": EXCLUDED_TABLES,
            }
            fp.write("{\n")
            for key, value in header.items():
                fp.write(f"{_dumps(key)}: {_dumps(value)},\n")
            fp.write('"tables": {')
            tables = [t for t in SQLModel.metadata.sorted_tables if not _is_excluded(t.name)]
            for i, table in enumerate(tables):
                fp.write(("," if i else "") + f"\n{_dumps(table.name)}: [")
                db_columns = (
                    {c["name"] for c in inspector.get_columns(table.name)}
                    if table.name in present
                    else set()
                )
                for j, row in enumerate(_rows(conn, table, db_columns)):
                    fp.write(("," if j else "") + "\n" + _dumps(row))
                fp.write("]")
            fp.write("\n}\n}\n")
    finally:
        engine.dispose()


def export_record(dest: Path, *, database_url: str | None = None) -> Path:
    """Write the JSON export of the live db to `dest` (must not exist).

    Reads a private snapshot rather than the live db: pysqlite runs each SELECT in its own
    implicit transaction, so reading the live db table by table could mix two instants.
    """
    source = _live_db(database_url)
    dest = Path(dest)
    partial = _claim(dest)
    try:
        with tempfile.TemporaryDirectory(prefix="aa-export-") as scratch:
            snap = Path(scratch) / "snapshot.db"
            _copy_db(source, snap)
            with partial.open("w", encoding="utf-8") as fp:
                write_export(fp, snap)
        os.replace(partial, dest)
    except sqlite3.Error as exc:
        raise BackupError(f"export failed: {exc}") from exc
    finally:
        partial.unlink(missing_ok=True)
    return dest


# --- restore ------------------------------------------------------------------------------


def _check_snapshot(source: Path) -> None:
    if not source.is_file():
        raise BackupError(f"{source} does not exist")
    with source.open("rb") as fh:
        if fh.read(len(_SQLITE_MAGIC)) != _SQLITE_MAGIC:
            raise BackupError(f"{source} is not a SQLite database")
    conn = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        status = conn.execute("PRAGMA quick_check").fetchone()[0]
        has_topic = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='topic'"
        ).fetchone()
    except sqlite3.Error as exc:
        raise BackupError(f"{source} is not a readable SQLite database: {exc}") from exc
    finally:
        conn.close()
    if status != "ok":
        raise BackupError(f"{source} failed SQLite's integrity check: {status}")
    if not has_topic:
        raise BackupError(f"{source} does not look like an Adaptive Academy database")


def restore(
    source: Path,
    *,
    database_url: str | None = None,
    force: bool = False,
    backup_dir: Path = Path("backups"),
) -> Path | None:
    """Copy the snapshot `source` over the live db. Returns the pre-restore snapshot, if any.

    Stop the app first. The copy goes through SQLite's backup API (not a file copy), so a stale
    -wal beside the target can never be replayed onto the restored pages. Afterwards run
    `alembic upgrade head` to bring an older snapshot up to the current schema.
    """
    source = Path(source).absolute()
    target = sqlite_path(database_url)
    _check_snapshot(source)
    if target.exists() and source.resolve() == target.resolve():
        raise BackupError("cannot restore the database onto itself")
    pre_restore: Path | None = None
    if target.exists():
        if not force:
            raise BackupError(
                f"{target} already exists; pass --force to replace it "
                "(the current db is backed up first)"
            )
        backup_dir.mkdir(parents=True, exist_ok=True)
        pre_restore = snapshot(
            backup_dir / f"adaptive_academy-pre-restore-{timestamp()}.db",
            database_url=f"sqlite:///{target}",
        )
    elif not target.parent.is_dir():
        raise BackupError(f"directory {target.parent} does not exist")
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(target, timeout=SQLITE_BUSY_TIMEOUT_S)
        try:
            src.backup(dst)
        finally:
            dst.close()
    except sqlite3.Error as exc:
        raise BackupError(f"restore failed: {exc}") from exc
    finally:
        src.close()
    return pre_restore
