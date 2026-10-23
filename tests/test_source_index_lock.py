"""Background source indexing holds no write lock while a source is embedded.

Walkthrough review 2026-10-23: index_accepted_sources flushed the chunk rows (taking the
SQLite write lock), embedded them inside the same transaction, and committed after. With the
local ONNX embedder a large source takes seconds to tens of seconds, so a second "Save
reading list", a tutor message or a delete could hit "database is locked" (busy timeout
30 s). These tests write from a second connection *during* the embed call.
"""
from __future__ import annotations

import importlib.util
import sqlite3
import time

import pytest
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine, select

from adaptive_academy import db
from adaptive_academy.engine.memory import index_accepted_sources
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.llm.hybrid_retriever import HybridRetriever
from adaptive_academy.llm.scripted_embedder import ScriptedEmbedder
from adaptive_academy.models import AgentEvent, Chunk, SourceDoc, Topic

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("sqlite_vec") is None,
    reason="sqlite-vec optional extra is unavailable",
)

SOURCE_TEXT = ("para " * 200 + "\n\n") * 12


@pytest.fixture
def file_db(tmp_path):
    path = str(tmp_path / "index.db")
    engine = create_engine(f"sqlite:///{path}", connect_args=db.CONNECT_ARGS)

    @event.listens_for(engine, "connect")
    def _pragmas(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA journal_mode=WAL")
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    assert db.ensure_fts(engine) is True
    assert db.ensure_vec(engine) is True
    with Session(engine) as session:
        topic = Topic(title="T")
        session.add(topic)
        session.flush()
        doc = SourceDoc(topic_id=topic.id, title="D", url="https://e.com/x", status="accepted")
        session.add(doc)
        session.commit()
        ids = (topic.id, doc.id)
    yield engine, path, *ids
    engine.dispose()


def _write_from_second_connection(path: str, sql: str, params: tuple = ()) -> str:
    """Run one write on a fresh connection with a short busy timeout; say if it got through."""
    conn = sqlite3.connect(path, timeout=0.2)
    try:
        conn.execute(sql, params)
        conn.commit()
        return "written"
    except sqlite3.OperationalError as exc:
        return f"blocked: {exc}"
    finally:
        conn.close()


class SlowEmbedder(ScriptedEmbedder):
    """The deterministic embedder, but slow, with a hook that runs mid-embedding."""

    def __init__(self, during):
        super().__init__()
        self.during = during
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        self.during(self.calls)
        time.sleep(0.05)
        return super().embed(texts)


def _retriever(embedder) -> HybridRetriever:
    return HybridRetriever(FtsRetriever(), embedder)


def test_a_second_connection_can_write_while_a_source_is_embedded(file_db):
    engine, path, _topic_id, doc_id = file_db
    seen: list[str] = []
    embedder = SlowEmbedder(lambda _call: seen.append(_write_from_second_connection(
        path, "INSERT INTO topic(title, created_at, is_demo) VALUES ('other', '2026-01-01', 0)")))

    index_accepted_sources(engine, [doc_id], fetch=lambda _url: SOURCE_TEXT,
                           retriever=_retriever(embedder))

    assert seen and all(result == "written" for result in seen), seen
    with Session(engine) as session:
        chunks = session.exec(select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc_id}")).all()
        assert chunks
        assert {chunk.embedding_model for chunk in chunks} == {"scripted"}
        vectors = session.execute(text("SELECT count(*) FROM chunk_vec")).scalar_one()
        assert vectors == len(chunks)
        assert session.exec(select(Topic).where(Topic.title == "other")).all()


def test_a_chunk_changed_during_embedding_gets_no_stale_vector(file_db):
    engine, path, _topic_id, doc_id = file_db
    seen: list[str] = []

    def change_first_chunk(call: int) -> None:
        if call == 1:
            seen.append(_write_from_second_connection(
                path, "UPDATE chunk SET text = 'rewritten meanwhile' WHERE id = "
                      "(SELECT min(id) FROM chunk WHERE source_ref = ?)",
                (f"sourcedoc:{doc_id}",)))

    index_accepted_sources(engine, [doc_id], fetch=lambda _url: SOURCE_TEXT,
                           retriever=_retriever(SlowEmbedder(change_first_chunk)))

    assert seen == ["written"]
    with Session(engine) as session:
        chunks = session.exec(
            select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc_id}").order_by(Chunk.id)
        ).all()
        first, rest = chunks[0], chunks[1:]
        assert first.text == "rewritten meanwhile"
        assert first.embedding_model is None  # left for a reindex, never a vector of old text
        assert session.execute(
            text("SELECT count(*) FROM chunk_vec WHERE chunk_id = :id"), {"id": first.id}
        ).scalar_one() == 0
        assert rest and all(chunk.embedding_model == "scripted" for chunk in rest)


def test_an_embedder_failure_keeps_the_chunks_and_logs_an_error(file_db):
    engine, _path, topic_id, doc_id = file_db

    class Broken(ScriptedEmbedder):
        def embed(self, texts):
            raise RuntimeError("model missing")

    index_accepted_sources(engine, [doc_id], fetch=lambda _url: SOURCE_TEXT,
                           retriever=_retriever(Broken()))

    with Session(engine) as session:
        chunks = session.exec(select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc_id}")).all()
        assert chunks and all(chunk.embedding_model is None for chunk in chunks)
        [error] = session.exec(select(AgentEvent).where(AgentEvent.kind == "memory:error")).all()
        assert error.topic_id == topic_id
        assert "RuntimeError: model missing" in error.detail
        assert not session.exec(
            select(AgentEvent).where(AgentEvent.kind == "memory:index_skipped")).all()


def test_an_opaque_on_index_hook_starts_with_no_write_held(file_db):
    """A retriever with only on_index (the reviewer's probe) is called after the rows commit."""
    engine, path, _topic_id, doc_id = file_db
    seen: list[str] = []

    class SlowHook:
        name = "slow"

        def on_index(self, session, chunk_ids):
            seen.append(_write_from_second_connection(
                path, "INSERT INTO topic(title, created_at, is_demo) "
                      "VALUES ('x', '2026-01-01', 0)"))

    index_accepted_sources(engine, [doc_id], fetch=lambda _url: SOURCE_TEXT,
                           retriever=SlowHook())

    assert seen and all(result == "written" for result in seen), seen
