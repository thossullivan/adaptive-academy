import logging
from collections.abc import Iterator
import sqlite3

from sqlalchemy import Engine, event
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlmodel import Session, SQLModel, create_engine

from adaptive_academy.settings import settings

try:
    import sqlite_vec
except ImportError:
    sqlite_vec = None

logger = logging.getLogger(__name__)

# SQLite serializes writers. sqlite3's default busy timeout (5 s) turned a long agent run
# into 500 "database is locked" for every concurrent writer (UAT 2026-08-28, F5). Engine
# paths also commit before every researcher/LLM call so no write lock spans a network
# round trip; the timeout covers the short overlaps that remain.
SQLITE_BUSY_TIMEOUT_S = 30
CONNECT_ARGS: dict = {"check_same_thread": False, "timeout": SQLITE_BUSY_TIMEOUT_S}

engine = create_engine(
    settings.database_url,
    connect_args=CONNECT_ARGS,
)

FTS_DDL: list[str] = [
    """
    CREATE VIRTUAL TABLE IF NOT EXISTS chunk_fts USING fts5(
        context,
        text,
        content='chunk',
        content_rowid='id',
        tokenize='porter unicode61'
    )
    """.strip(),
    """
    CREATE TRIGGER IF NOT EXISTS chunk_ai AFTER INSERT ON chunk BEGIN
        INSERT INTO chunk_fts(rowid, context, text)
        VALUES (new.id, new.context, new.text);
    END
    """.strip(),
    """
    CREATE TRIGGER IF NOT EXISTS chunk_ad AFTER DELETE ON chunk BEGIN
        INSERT INTO chunk_fts(chunk_fts, rowid, context, text)
        VALUES ('delete', old.id, old.context, old.text);
    END
    """.strip(),
    """
    CREATE TRIGGER IF NOT EXISTS chunk_au AFTER UPDATE ON chunk BEGIN
        INSERT INTO chunk_fts(chunk_fts, rowid, context, text)
        VALUES ('delete', old.id, old.context, old.text);
        INSERT INTO chunk_fts(rowid, context, text)
        VALUES (new.id, new.context, new.text);
    END
    """.strip(),
]


@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, _):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    ensure_fts(engine)
    ensure_vec(engine)
    ensure_graph_backfill(engine)


def ensure_graph_backfill(db_engine: Engine) -> bool:
    """Populate ConceptEdge from existing foundations/aliases at startup (idempotent), so a
    database upgraded in place gets its graph without a manual `just graph-backfill`."""
    from sqlmodel import Session

    from adaptive_academy.engine.graph import backfill

    try:
        with Session(db_engine) as session:
            result = backfill(session)
            session.commit()
    except Exception as exc:  # noqa: BLE001 - startup must never crash on graph state
        logger.warning("graph backfill skipped: %s", exc)
        return False
    if result.edges:
        logger.info("graph backfill: tracks=%s edges=%s unresolved=%s",
                    result.tracks, result.edges, result.unresolved)
    return True


def ensure_fts(db_engine: Engine) -> bool:
    """Create the FTS5 shadow table and triggers when FTS5 is available.

    If chunks were written while FTS5 was unavailable (triggers absent), the external-content
    index is stale; the integrity check detects that and a `rebuild` re-indexes every row.
    """
    try:
        with db_engine.begin() as connection:
            existed = connection.exec_driver_sql(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='chunk_fts'"
            ).first() is not None
            for statement in FTS_DDL:
                connection.exec_driver_sql(statement)
            if not existed:
                # FTS5's integrity-check does not compare an external-content index against
                # its content table, so a freshly created index is rebuilt unconditionally:
                # rows written while FTS5 was unavailable become searchable.
                connection.exec_driver_sql("INSERT INTO chunk_fts(chunk_fts) VALUES('rebuild')")
                logger.info("chunk_fts created and rebuilt from existing chunk rows")
    except OperationalError:
        return False
    return True


def ensure_vec(db_engine: Engine) -> bool:
    """Load sqlite-vec and create its chunk vector table when available."""
    if sqlite_vec is None:
        _drop_vec_triggers(db_engine)
        return False

    newly_registered = not event.contains(db_engine, "connect", _load_vec_extension)
    if newly_registered:
        event.listen(db_engine, "connect", _load_vec_extension)
    try:
        with db_engine.begin() as connection:
            raw_connection = connection.connection.driver_connection
            _load_vec_extension(raw_connection, None)
            connection.exec_driver_sql(
                "CREATE VIRTUAL TABLE IF NOT EXISTS chunk_vec "
                "USING vec0(chunk_id INTEGER PRIMARY KEY, embedding float[384])"
            )
            # Chunks deleted while the extension was unavailable (triggers dropped) left
            # their vectors behind; purge them before the trigger takes over again.
            connection.exec_driver_sql(
                "DELETE FROM chunk_vec WHERE chunk_id NOT IN (SELECT id FROM chunk)"
            )
            for statement in VEC_TRIGGER_DDL.values():
                connection.exec_driver_sql(statement)
    except (AttributeError, OSError, sqlite3.Error, SQLAlchemyError):
        if newly_registered:
            event.remove(db_engine, "connect", _load_vec_extension)
        _drop_vec_triggers(db_engine)
        return False
    return True


# Triggers on `chunk` whose bodies touch the vec0 table. SQLite compiles a trigger body when
# the triggering statement runs, so on a connection WITHOUT sqlite-vec loaded every chunk
# delete would fail with "no such module: vec0" (the memory extra is optional). They exist
# only while the extension loads; ensure_vec drops them otherwise.
VEC_TRIGGER_DDL: dict[str, str] = {
    "chunk_vec_ad": (
        "CREATE TRIGGER IF NOT EXISTS chunk_vec_ad AFTER DELETE ON chunk BEGIN "
        "DELETE FROM chunk_vec WHERE chunk_id = old.id; END"
    ),
}


def _drop_vec_triggers(db_engine: Engine) -> None:
    """Without sqlite-vec, remove the vec triggers so chunk deletes keep working. Dropping a
    trigger does not compile its body, so this needs no extension. The orphaned vectors this
    leaves are never ranked (the vector leg only considers ids still in `chunk`) and are
    purged by the next ensure_vec that loads the extension."""
    try:
        with db_engine.begin() as connection:
            for name in VEC_TRIGGER_DDL:
                connection.exec_driver_sql(f"DROP TRIGGER IF EXISTS {name}")
    except SQLAlchemyError as exc:  # startup must never crash on this
        logger.warning("could not drop the sqlite-vec triggers: %s", exc)


def _load_vec_extension(dbapi_connection, _) -> None:
    if sqlite_vec is None:
        return
    dbapi_connection.enable_load_extension(True)
    try:
        sqlite_vec.load(dbapi_connection)
    finally:
        dbapi_connection.enable_load_extension(False)


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
