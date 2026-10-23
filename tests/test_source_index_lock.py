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
import threading
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, col, create_engine, select

from adaptive_academy import db
from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_fetcher, get_retriever, get_session
from adaptive_academy.engine.memory import (
    SOURCES_IN_FLIGHT,
    index_accepted_sources,
    index_text,
    reindex_topic,
)
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


def _more_sources(engine, topic_id: int, n: int) -> list[int]:
    with Session(engine) as session:
        docs = [SourceDoc(topic_id=topic_id, title=f"S{i}", url=f"https://e.com/s{i}",
                          status="accepted") for i in range(n)]
        session.add_all(docs)
        session.commit()
        return [doc.id for doc in docs]


def test_two_tasks_over_the_same_sources_fetch_each_once(file_db):
    """The reviewer's dupprobe: two background tasks for the same three sources (two quick
    saves) fetched each source twice. A source one task is working on is skipped by the
    other, and one already indexed is not fetched again."""
    engine, _path, topic_id, _doc_id = file_db
    ids = _more_sources(engine, topic_id, 3)
    fetches: list[str] = []

    def fetch(url: str) -> str:
        fetches.append(url)
        time.sleep(0.05)
        return SOURCE_TEXT

    retriever = _retriever(SlowEmbedder(lambda _call: None))
    threads = [threading.Thread(target=index_accepted_sources, args=(engine, ids),
                                kwargs={"fetch": fetch, "retriever": retriever})
               for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(fetches) == sorted(f"https://e.com/s{i}" for i in range(3))
    assert not [source_id for source_id in ids if source_id in SOURCES_IN_FLIGHT]
    with Session(engine) as session:
        chunks = session.exec(select(Chunk)).all()
        assert chunks and {chunk.embedding_model for chunk in chunks} == {"scripted"}
        assert session.execute(text("SELECT count(*) FROM chunk_vec")).scalar_one() == len(chunks)


def _client(engine, *, fetch, retriever) -> TestClient:
    def session_dep():
        with Session(engine) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_session] = session_dep
    app.dependency_overrides[get_fetcher] = lambda: fetch
    app.dependency_overrides[get_retriever] = lambda: retriever
    return TestClient(app)


def test_a_second_save_while_the_first_is_indexing_fetches_each_source_once(file_db):
    engine, _path, topic_id, doc_id = file_db
    ids = [doc_id, *_more_sources(engine, topic_id, 2)]
    fetches: list[str] = []
    first_fetch_started = threading.Event()
    second_save_done = threading.Event()

    def fetch(url: str) -> str:
        fetches.append(url)
        if len(fetches) == 1:  # the first save's task, on its first source
            first_fetch_started.set()
            assert second_save_done.wait(10)
        return SOURCE_TEXT

    client = _client(engine, fetch=fetch, retriever=_retriever(ScriptedEmbedder()))
    body = {"accepted_ids": ids, "pruned_ids": []}
    url = f"/api/topics/{topic_id}/sources/review"
    first: dict = {}
    saver = threading.Thread(target=lambda: first.setdefault("resp", client.post(url, json=body)))
    saver.start()
    assert first_fetch_started.wait(10)
    second = client.post(url, json=body)
    second_save_done.set()
    saver.join(10)

    assert second.status_code == first["resp"].status_code == 200
    assert sorted(fetches) == sorted(["https://e.com/x", "https://e.com/s0", "https://e.com/s1"])
    with Session(engine) as session:
        refs = set(session.exec(select(Chunk.source_ref)).all())
        assert refs == {f"sourcedoc:{source_id}" for source_id in ids}
        assert not session.exec(
            select(Chunk).where(col(Chunk.embedding_model).is_(None))).all()


def test_a_save_embeds_chunks_left_without_a_vector(file_db):
    """Chunks whose embedding failed or was cut short (embedding_model NULL) are embedded on
    the next save, without fetching the source again."""
    engine, _path, topic_id, doc_id = file_db
    with Session(engine) as session:
        index_text(session, kind="source_doc", text=SOURCE_TEXT, source_ref=f"sourcedoc:{doc_id}",
                   topic_id=topic_id, defer_embedding=True)
        session.commit()
        assert session.exec(select(Chunk)).all()
    fetches: list[str] = []
    client = _client(engine, fetch=lambda u: fetches.append(u) or SOURCE_TEXT,
                     retriever=_retriever(ScriptedEmbedder()))

    resp = client.post(f"/api/topics/{topic_id}/sources/review",
                       json={"accepted_ids": [doc_id], "pruned_ids": []})

    assert resp.status_code == 200
    assert fetches == []
    with Session(engine) as session:
        chunks = session.exec(select(Chunk)).all()
        assert {chunk.embedding_model for chunk in chunks} == {"scripted"}
        assert session.execute(text("SELECT count(*) FROM chunk_vec")).scalar_one() == len(chunks)


def test_a_save_skips_a_source_another_task_is_indexing(file_db):
    engine, _path, topic_id, doc_id = file_db
    fetches: list[str] = []
    client = _client(engine, fetch=lambda u: fetches.append(u) or SOURCE_TEXT,
                     retriever=_retriever(ScriptedEmbedder()))
    assert SOURCES_IN_FLIGHT.claim(doc_id)
    try:
        resp = client.post(f"/api/topics/{topic_id}/sources/review",
                           json={"accepted_ids": [doc_id], "pruned_ids": []})
    finally:
        SOURCES_IN_FLIGHT.release(doc_id)

    assert resp.status_code == 200
    assert fetches == []


def test_reindex_holds_no_write_lock_while_a_source_is_embedded(file_db, tmp_path):
    engine, path, topic_id, doc_id = file_db
    seen: list[str] = []
    embedder = SlowEmbedder(lambda _call: seen.append(_write_from_second_connection(
        path, "INSERT INTO topic(title, created_at, is_demo) VALUES ('other', '2026-01-01', 0)")))

    with Session(engine) as session:
        result = reindex_topic(session, topic_id, vault_path=str(tmp_path),
                               fetch=lambda _url: SOURCE_TEXT, kinds=("source_doc",),
                               retriever=_retriever(embedder))

    assert result.indexed > 0
    assert seen and all(outcome == "written" for outcome in seen), seen
    with Session(engine) as session:
        chunks = session.exec(select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc_id}")).all()
        assert chunks and {chunk.embedding_model for chunk in chunks} == {"scripted"}
        assert session.execute(text("SELECT count(*) FROM chunk_vec")).scalar_one() == len(chunks)
