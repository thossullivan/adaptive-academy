import importlib.util
import json
import struct
import time

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_fetcher, get_llm, get_retriever, get_session
from adaptive_academy.db import ensure_fts, ensure_vec
from adaptive_academy.engine.memory import (
    ChunkFilter,
    content_hash,
    index_text,
    is_near_duplicate,
    jaccard,
    reindex_topic,
    remove_source,
    split_plain,
)
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.llm.hybrid_retriever import HybridRetriever
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.retriever_types import Hit
from adaptive_academy.llm.scripted_embedder import ScriptedEmbedder
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import (
    AgentEvent,
    Chunk,
    Concept,
    KnowledgeEstimate,
    SourceDoc,
    Topic,
    TopicFoundation,
    Track,
)

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


def test_index_text_embedding_failure_is_fail_open(vec_session):
    session = vec_session
    topic = Topic(title="Fail-open embeddings")
    session.add(topic)
    session.flush()

    class FailingEmbedder:
        name = "failing"
        dim = 384

        def embed(self, texts):
            raise RuntimeError("embedding failed")

    retriever = HybridRetriever(FtsRetriever(), FailingEmbedder())

    result = index_text(
        session,
        kind="vault_note",
        text="The chunk remains available to lexical retrieval.",
        source_ref="test:fail-open",
        topic_id=topic.id,
        retriever=retriever,
    )
    session.commit()

    chunk = session.exec(select(Chunk).where(Chunk.source_ref == "test:fail-open")).one()
    event_row = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:error")
    ).one()
    assert result.indexed == 1
    assert chunk.embedding_model is None
    assert event_row.topic_id == topic.id
    assert event_row.detail == "embed: RuntimeError: embedding failed"


def test_chunk_delete_trigger_prevents_stale_vector_on_rowid_reuse(vec_session):
    session = vec_session
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    index_text(
        session,
        kind="vault_note",
        text="obsolete quasar vector",
        source_ref="test:old-row",
        retriever=retriever,
    )
    session.commit()
    old_chunk = session.exec(
        select(Chunk).where(Chunk.source_ref == "test:old-row")
    ).one()
    old_id = old_chunk.id
    assert old_id is not None

    assert remove_source(session, "test:old-row") == 1
    session.commit()
    index_text(
        session,
        kind="learner_output",
        text="replacement content",
        source_ref="test:new-row",
    )
    session.commit()
    new_chunk = session.exec(
        select(Chunk).where(Chunk.source_ref == "test:new-row")
    ).one()

    vector = session.execute(
        text("SELECT chunk_id FROM chunk_vec WHERE chunk_id = :chunk_id"),
        {"chunk_id": old_id},
    ).first()
    hits = retriever.search(
        session,
        "obsolete quasar vector",
        where=ChunkFilter(),
        k=1,
    )
    assert new_chunk.id == old_id
    assert vector is None
    assert hits == []


def test_review_sources_embeds_accepted_source_at_write_time(vec_session):
    session = vec_session
    topic = Topic(title="Accepted source")
    session.add(topic)
    session.flush()
    source = SourceDoc(
        topic_id=topic.id,
        title="Source",
        url="https://example.test/source",
        status="proposed",
    )
    session.add(source)
    session.commit()
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_fetcher] = lambda: lambda _: "Embedded source text."
    app.dependency_overrides[get_retriever] = lambda: retriever

    response = TestClient(app).post(
        f"/api/topics/{topic.id}/sources/review",
        json={"accepted_ids": [source.id], "pruned_ids": []},
    )
    app.dependency_overrides.clear()

    chunk = session.exec(select(Chunk).where(Chunk.source_ref == f"sourcedoc:{source.id}")).one()
    assert response.status_code == 200
    assert chunk.embedding_model == retriever.embedder.name


def test_assess_route_embeds_scheduled_decay_question(vec_session):
    session = vec_session
    topic = Topic(title="Decay")
    session.add(topic)
    session.flush()
    session.add(
        TopicFoundation(
            topic_id=topic.id,
            overview="Overview",
            key_concepts=["retrieval"],
            prerequisite_map={},
        )
    )
    track = Track(topic_id=topic.id, title="Track")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="retrieval")
    session.add(concept)
    session.flush()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high"))
    session.commit()
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    rubric = json.dumps(
        {
            "criteria": ["clear"],
            "must_include": [],
            "strong_signs": [],
            "weak_signs": [],
            "source_refs": [],
        }
    )
    grade = json.dumps({"score": 0.8, "verdict": "solid", "gaps": []})
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text=rubric), LLMResponse(text=grade)]
    )
    app.dependency_overrides[get_retriever] = lambda: retriever

    response = TestClient(app).post(
        f"/api/concepts/{concept.id}/assess",
        json={"kind": "self_explanation", "response": "Retrieval selects evidence."},
    )
    app.dependency_overrides.clear()

    chunk = session.exec(
        select(Chunk).where(Chunk.source_ref.startswith("recallprompt:"))
    ).one()
    assert response.status_code == 200
    assert chunk.embedding_model == retriever.embedder.name


def test_vault_ingest_route_embeds_notes_at_write_time(vec_session, tmp_path):
    session = vec_session
    topic = Topic(title="Vault ingest")
    session.add(topic)
    session.commit()
    note = tmp_path / "note.md"
    note.write_text("# Note\n\nEmbedded vault content.", encoding="utf-8")
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_retriever] = lambda: retriever

    response = TestClient(app).post(
        f"/api/topics/{topic.id}/vault/ingest",
        json={"vault_path": str(tmp_path)},
    )
    app.dependency_overrides.clear()

    chunk = session.exec(select(Chunk).where(Chunk.kind == "vault_note")).one()
    assert response.status_code == 200
    assert chunk.embedding_model == retriever.embedder.name


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


def test_reindex_reembeds_stale_chunks_outside_selected_kinds(vec_session, tmp_path):
    session = vec_session
    topic = Topic(title="All stale kinds")
    session.add(topic)
    session.flush()
    index_text(
        session,
        kind="learner_output",
        text="Learner output needs a vector.",
        source_ref="test:learner-output",
        topic_id=topic.id,
    )
    session.commit()
    chunk = session.exec(
        select(Chunk).where(Chunk.source_ref == "test:learner-output")
    ).one()
    assert chunk.embedding_model is None
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())

    reindex_topic(
        session,
        topic.id,
        vault_path=str(tmp_path),
        fetch=lambda _: None,
        kinds=("vault_note",),
        retriever=retriever,
    )
    session.refresh(chunk)

    assert chunk.embedding_model == retriever.embedder.name


def test_reindex_batches_stale_embeddings_and_honors_deadline(vec_session):
    session = vec_session
    topic = Topic(title="Embedding deadline")
    session.add(topic)
    session.flush()
    for index in range(130):
        index_text(
            session,
            kind="learner_output",
            text=f"Learner output {index}",
            source_ref=f"test:deadline:{index}",
            topic_id=topic.id,
        )
    session.commit()

    class SlowEmbedder:
        name = "slow-scripted"
        dim = 384

        def __init__(self):
            self.inner = ScriptedEmbedder()
            self.batch_sizes = []

        def embed(self, texts):
            self.batch_sizes.append(len(texts))
            time.sleep(0.02)
            return self.inner.embed(texts)

    embedder = SlowEmbedder()
    retriever = HybridRetriever(FtsRetriever(), embedder)
    result = reindex_topic(
        session,
        topic.id,
        vault_path="",
        fetch=lambda _: None,
        kinds=("source_doc",),
        deadline_s=0.005,
        retriever=retriever,
    )

    chunks = session.exec(
        select(Chunk).where(Chunk.topic_id == topic.id).order_by(Chunk.id)
    ).all()
    embedded = [chunk for chunk in chunks if chunk.embedding_model == embedder.name]
    stale = [chunk for chunk in chunks if chunk.embedding_model is None]
    assert result.truncated is True
    assert embedder.batch_sizes == [64]
    assert embedded
    assert stale


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
