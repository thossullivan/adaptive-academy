import importlib.util
import struct

import pytest
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from adaptive_academy.db import ensure_fts, ensure_vec
from adaptive_academy.engine.memory import (
    content_hash,
    index_text,
    is_near_duplicate,
    jaccard,
    reindex_topic,
    split_plain,
)
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.llm.hybrid_retriever import HybridRetriever
from adaptive_academy.llm.retriever_types import Hit
from adaptive_academy.llm.scripted_embedder import ScriptedEmbedder
from adaptive_academy.models import Chunk, SourceDoc, Topic

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("sqlite_vec") is None,
    reason="sqlite-vec optional extra is unavailable",
)


@pytest.fixture
def vec_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, _):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    SQLModel.metadata.create_all(engine)
    assert ensure_fts(engine) is True
    assert ensure_vec(engine) is True
    with Session(engine) as session:
        yield session


def _split_small(value: str):
    return split_plain(value, target=15)


def _vector_row(session: Session, chunk_id: int) -> list[float]:
    blob = session.execute(
        text("SELECT embedding FROM chunk_vec WHERE chunk_id = :chunk_id"),
        {"chunk_id": chunk_id},
    ).scalar_one()
    return list(struct.unpack("<384f", blob))


def _colliding_token(embedder: ScriptedEmbedder, token: str) -> str:
    target = embedder.embed([token])[0]
    for index in range(10_000):
        candidate = f"different{index}"
        if candidate != token and embedder.embed([candidate])[0] == target:
            return candidate
    raise AssertionError("could not find a deterministic hashing collision")


def test_index_text_embeds_changed_chunks_and_removes_orphan_vectors(vec_session):
    session = vec_session
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    source_ref = "test:pieces"

    first = index_text(
        session,
        kind="vault_note",
        text="alpha one\n\nbravo two\n\ncharlie three",
        source_ref=source_ref,
        splitter=_split_small,
        retriever=retriever,
    )
    second = index_text(
        session,
        kind="vault_note",
        text="alpha one",
        source_ref=source_ref,
        splitter=_split_small,
        retriever=retriever,
    )

    chunks = session.exec(select(Chunk).where(Chunk.source_ref == source_ref)).all()
    vector_count = session.execute(text("SELECT count(*) FROM chunk_vec")).scalar_one()
    assert first.indexed == 3
    assert second.removed == 2
    assert len(chunks) == vector_count == 1
    assert chunks[0].embedding_model == retriever.embedder.name


def test_reindex_reembeds_a_chunk_with_a_stale_model(vec_session):
    session = vec_session
    topic = Topic(title="Re-embedding")
    session.add(topic)
    session.flush()
    assert topic.id is not None
    doc = SourceDoc(
        topic_id=topic.id,
        title="Vectors",
        url="https://example.test/vectors",
        status="accepted",
    )
    session.add(doc)
    session.commit()

    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    first = reindex_topic(
        session,
        topic.id,
        vault_path="",
        fetch=lambda _: "semantic vector text",
        kinds=("source_doc",),
        retriever=retriever,
    )
    chunk = session.exec(select(Chunk).where(Chunk.source_ref == f"sourcedoc:{doc.id}")).one()
    assert chunk.id is not None
    expected = retriever.embedder.embed([f"{chunk.context}\n{chunk.text}"])[0]
    assert first.indexed == 1
    assert _vector_row(session, chunk.id) == pytest.approx(expected)

    session.execute(
        text("DELETE FROM chunk_vec WHERE chunk_id = :chunk_id"),
        {"chunk_id": chunk.id},
    )
    session.execute(
        text(
            "INSERT INTO chunk_vec(chunk_id, embedding) "
            "VALUES (:chunk_id, :embedding)"
        ),
        {
            "chunk_id": chunk.id,
            "embedding": struct.pack("<384f", *([0.0] * 384)),
        },
    )
    chunk.embedding_model = "obsolete-model"
    session.add(chunk)
    session.commit()

    second = reindex_topic(
        session,
        topic.id,
        vault_path="",
        fetch=lambda _: "semantic vector text",
        kinds=("source_doc",),
        retriever=retriever,
    )
    session.refresh(chunk)

    assert second.indexed == 0
    assert second.skipped == 1
    assert chunk.embedding_model == retriever.embedder.name
    assert _vector_row(session, chunk.id) == pytest.approx(expected)


def test_is_near_duplicate_can_match_on_cosine_alone():
    embedder = ScriptedEmbedder()
    original = "cosine"
    candidate = _colliding_token(embedder, original)
    chunk = Chunk(
        id=1,
        kind="question",
        source_ref="question:prior",
        text=original,
        content_hash=content_hash(original),
    )
    hit = Hit(chunk=chunk, score=1.0)

    assert jaccard(candidate, original) == 0.0
    assert is_near_duplicate(candidate, [hit], embedder=embedder) is hit
