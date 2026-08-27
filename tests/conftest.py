import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from adaptive_academy.api import deps as api_deps
from adaptive_academy.db import ensure_fts


@pytest.fixture(autouse=True)
def _block_live_source_fetch(monkeypatch):
    """Keep route tests offline unless they explicitly override the fetch dependency."""
    monkeypatch.setattr(api_deps, "fetch_artifact_text", lambda _: None)


@pytest.fixture(autouse=True)
def _offline_retriever(monkeypatch):
    """Route tests never construct the live embedder: the default retriever is scripted and
    model downloads are disabled for the whole test process. Tests that want the hybrid
    path build it explicitly with ScriptedEmbedder."""
    monkeypatch.setattr(api_deps.settings, "retriever", "scripted")
    monkeypatch.setattr(api_deps.settings, "embedding_allow_download", False)
    api_deps.reset_retriever_cache()
    yield
    api_deps.reset_retriever_cache()


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    SQLModel.metadata.create_all(engine)
    ensure_fts(engine)
    with Session(engine) as s:
        yield s
