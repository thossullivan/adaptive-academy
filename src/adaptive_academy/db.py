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

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False},
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
    """Create the FTS5 shadow table and triggers when FTS5 is available."""
    try:
        with db_engine.begin() as connection:
            for statement in FTS_DDL:
                connection.exec_driver_sql(statement)
    except OperationalError:
        return False
    return True


def ensure_vec(db_engine: Engine) -> bool:
    """Load sqlite-vec and create its chunk vector table when available."""
    if sqlite_vec is None:
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
            connection.exec_driver_sql(
                "DELETE FROM chunk_vec WHERE chunk_id NOT IN (SELECT id FROM chunk)"
            )
            connection.exec_driver_sql(
                "CREATE TRIGGER IF NOT EXISTS chunk_vec_ad AFTER DELETE ON chunk BEGIN "
                "DELETE FROM chunk_vec WHERE chunk_id = old.id; END"
            )
    except (AttributeError, OSError, sqlite3.Error, SQLAlchemyError):
        if newly_registered:
            event.remove(db_engine, "connect", _load_vec_extension)
        return False
    return True


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
