import importlib.util
import math

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from adaptive_academy.db import ensure_fts, ensure_vec
from adaptive_academy.api.routes_memory import memory_stats
from adaptive_academy.engine.memory import ChunkFilter, content_hash
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.llm.hybrid_retriever import HybridRetriever
from adaptive_academy.llm.onnx_embedder import OnnxEmbedder, TextEmbedding
from adaptive_academy.llm.scripted_embedder import ScriptedEmbedder
from adaptive_academy.models import Chunk, Topic

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


def _chunk(text: str, source_ref: str, *, topic_id: int) -> Chunk:
    return Chunk(
        kind="vault_note",
        topic_id=topic_id,
        source_ref=source_ref,
        text=text,
        content_hash=content_hash(text),
    )


def _colliding_token(embedder: ScriptedEmbedder, token: str) -> str:
    target = embedder.embed([token])[0]
    for index in range(10_000):
        candidate = f"semantic{index}"
        if candidate != token and embedder.embed([candidate])[0] == target:
            return candidate
    raise AssertionError("could not find a deterministic hashing collision")


def test_scripted_embedder_is_deterministic_and_normalized():
    embedder = ScriptedEmbedder()

    first, second = embedder.embed(["stable vector", "stable vector"])

    assert first == second
    assert len(first) == 384
    assert math.sqrt(sum(value * value for value in first)) == pytest.approx(1.0)


@pytest.mark.skipif(TextEmbedding is None, reason="fastembed optional extra is unavailable")
def test_onnx_embedder_construction_does_not_load_the_model():
    embedder = OnnxEmbedder()

    assert embedder.name == "BAAI/bge-small-en-v1.5"
    assert embedder.dim == 384
    assert embedder._model is None


def test_hybrid_rrf_merges_exact_and_semantic_hits_with_filters(vec_session):
    session = vec_session
    included = Topic(title="Included")
    excluded = Topic(title="Excluded")
    session.add_all([included, excluded])
    session.flush()
    assert included.id is not None
    assert excluded.id is not None

    embedder = ScriptedEmbedder()
    semantic_token = _colliding_token(embedder, "quasar")
    exact = _chunk("quasar", "vault:exact", topic_id=included.id)
    semantic = _chunk(semantic_token, "vault:semantic", topic_id=included.id)
    wrong_topic = _chunk("quasar", "vault:wrong-topic", topic_id=excluded.id)
    session.add_all([exact, semantic, wrong_topic])
    session.flush()
    assert exact.id is not None
    assert semantic.id is not None
    assert wrong_topic.id is not None

    retriever = HybridRetriever(FtsRetriever(), embedder)
    retriever.on_index(session, [exact.id, semantic.id, wrong_topic.id])

    where = ChunkFilter(topic_id=included.id)
    first = retriever.search(session, "quasar", where=where, k=2)
    second = retriever.search(session, "quasar", where=where, k=2)

    assert first == second
    assert [chunk_id for chunk_id, _ in first] == [exact.id, semantic.id]
    assert wrong_topic.id not in [chunk_id for chunk_id, _ in first]
    assert first[0][1] == 1.0
    assert 0.0 < first[1][1] < first[0][1]


def test_hybrid_is_selected_when_both_optional_components_are_available(monkeypatch):
    from adaptive_academy.api import deps

    embedder = ScriptedEmbedder()
    monkeypatch.setattr(deps.settings, "retriever", "hybrid")
    monkeypatch.setattr(deps, "ensure_fts", lambda _engine: True)
    monkeypatch.setattr(deps, "ensure_vec", lambda _engine: True)
    monkeypatch.setattr(deps, "get_embedder", lambda: embedder)
    deps.reset_retriever_cache()

    retriever = deps.get_retriever()

    assert isinstance(retriever, HybridRetriever)
    assert retriever.embedder is embedder
    deps.reset_retriever_cache()


def test_get_embedder_uses_scripted_backend_for_scripted_retrieval(monkeypatch):
    from adaptive_academy.api import deps

    monkeypatch.setattr(deps.settings, "retriever", "scripted")

    assert isinstance(deps.get_embedder(), ScriptedEmbedder)


def test_memory_stats_reports_active_hybrid_retriever(vec_session):
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())

    stats = memory_stats(session=vec_session, retriever=retriever)

    assert stats.retriever == "hybrid"


def test_hybrid_degrades_once_when_the_embedder_is_unavailable(monkeypatch, caplog):
    from adaptive_academy.api import deps

    monkeypatch.setattr(deps.settings, "retriever", "hybrid")
    monkeypatch.setattr(deps, "ensure_fts", lambda _engine: True)
    monkeypatch.setattr(deps, "ensure_vec", lambda _engine: True)
    monkeypatch.setattr(
        deps,
        "get_embedder",
        lambda: (_ for _ in ()).throw(ImportError("fastembed unavailable")),
    )
    monkeypatch.setattr(deps, "_logged_retriever_degradations", set())
    deps.reset_retriever_cache()

    with caplog.at_level("WARNING"):
        first = deps.get_retriever()
        second = deps.get_retriever()

    assert isinstance(first, FtsRetriever)
    assert isinstance(second, FtsRetriever)
    assert caplog.messages.count("Hybrid retrieval is unavailable; using FTS5.") == 1
    deps.reset_retriever_cache()
