from collections.abc import Iterator

from sqlalchemy import Engine, event
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, SQLModel, create_engine

from adaptive_academy.settings import settings

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
    """Return vector-index availability after Task 9 implements setup."""
    return False


def get_session() -> Iterator[Session]:
    with Session(engine) as session:
        yield session
