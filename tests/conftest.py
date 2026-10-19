import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from adaptive_academy.api import deps as api_deps
from adaptive_academy.db import ensure_fts
from adaptive_academy.llm import usage as llm_usage


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


@pytest.fixture(autouse=True)
def _usage_bind_off(monkeypatch):
    """LLM usage rows go to the `session` fixture's in-memory engine when a test uses it,
    and nowhere otherwise — a test must never write usage into the real database file. No
    daily spending limit either, whatever the developer's .env says."""
    llm_usage.set_usage_bind(None)
    monkeypatch.setattr(llm_usage.settings, "daily_budget_usd", None)
    yield
    llm_usage.reset_usage_bind()


@pytest.fixture
def session(_usage_bind_off):
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
    llm_usage.set_usage_bind(engine)
    with Session(engine) as s:
        yield s
