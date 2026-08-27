import importlib.util
import math
import time

import pytest
from sqlalchemy import event
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from adaptive_academy.api.routes_memory import memory_stats
from adaptive_academy.db import ensure_fts, ensure_vec
from adaptive_academy.engine.memory import (
    ChunkFilter,
    _reembed_stale_chunks,
    content_hash,
)
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.llm.hybrid_retriever import HybridRetriever
from adaptive_academy.llm.onnx_embedder import (
    OnnxEmbedder,
    TextEmbedding,
    _model_is_cached,
)
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


def test_expired_stale_reembed_deadline_embeds_no_rows(vec_session):
    topic = Topic(title="Expired re-embed")
    vec_session.add(topic)
    vec_session.flush()
    chunk = _chunk("stale vector", "vault:stale", topic_id=topic.id)
    vec_session.add(chunk)
    vec_session.commit()

    class CountingEmbedder(ScriptedEmbedder):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def embed(self, texts):
            self.calls += 1
            return super().embed(texts)

    embedder = CountingEmbedder()
    retriever = HybridRetriever(FtsRetriever(), embedder)

    truncated = _reembed_stale_chunks(
        vec_session,
        retriever,
        topic_id=topic.id,
        deadline=time.perf_counter() - 1,
    )

    persisted = vec_session.exec(select(Chunk).where(Chunk.id == chunk.id)).one()
    assert truncated is True
    assert embedder.calls == 0
    assert persisted.embedding_model is None


@pytest.mark.skipif(TextEmbedding is None, reason="fastembed optional extra is unavailable")
def test_onnx_embedder_construction_does_not_load_the_model():
    embedder = OnnxEmbedder()

    assert embedder.name == "BAAI/bge-small-en-v1.5"
    assert embedder.dim == 384
    assert embedder._model is None


def test_onnx_embedder_reads_model_and_cache_settings_at_construction(monkeypatch):
    from adaptive_academy.llm import onnx_embedder

    calls = []

    class FakeVector:
        def tolist(self):
            return [0.0] * 384

    class RecordingTextEmbedding:
        def __init__(self, *, model_name, cache_dir, lazy_load, local_files_only=None):
            calls.append((model_name, cache_dir, lazy_load))

        def embed(self, texts):
            return [FakeVector() for _ in texts]

    monkeypatch.setattr(onnx_embedder, "TextEmbedding", RecordingTextEmbedding)
    monkeypatch.setattr(onnx_embedder.settings, "embedding_model", "first-model")
    monkeypatch.setattr(onnx_embedder.settings, "embedding_cache_dir", "/data/test-cache")
    embedder = OnnxEmbedder()
    monkeypatch.setattr(onnx_embedder.settings, "embedding_model", "second-model")
    monkeypatch.setattr(onnx_embedder.settings, "embedding_cache_dir", "/data/other-cache")

    embedder.embed(["text"])

    assert embedder.name == "first-model"
    assert calls == [("first-model", "/data/test-cache", True)]


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


def test_hybrid_returns_fts_results_when_vector_embedding_fails(vec_session, caplog, monkeypatch):
    from adaptive_academy.llm import hybrid_retriever

    class FailingEmbedder(ScriptedEmbedder):
        def embed(self, texts):
            raise RuntimeError("model cache is incomplete")

    topic = Topic(title="Fallback")
    vec_session.add(topic)
    vec_session.flush()
    assert topic.id is not None
    chunk = _chunk("lexical fallback", "vault:fallback", topic_id=topic.id)
    chunk.embedding_model = FailingEmbedder().name  # a current-model vector exists
    vec_session.add(chunk)
    vec_session.flush()
    where = ChunkFilter(topic_id=topic.id)
    fts = FtsRetriever()
    expected = fts.search(vec_session, "lexical fallback", where=where, k=3)
    retriever = HybridRetriever(fts, FailingEmbedder())
    monkeypatch.setattr(hybrid_retriever, "_logged_vector_failure", False)

    with caplog.at_level("WARNING"):
        first = retriever.search(vec_session, "lexical fallback", where=where, k=3)
        second = retriever.search(vec_session, "lexical fallback", where=where, k=3)

    assert expected
    assert first == second == expected
    assert caplog.messages.count(
        "Vector retrieval failed; returning FTS5 results."
    ) == 1


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


def test_get_retriever_reuses_one_cached_embedder(monkeypatch):
    from adaptive_academy.api import deps
    from adaptive_academy.llm import onnx_embedder

    class CountingEmbedder(ScriptedEmbedder):
        instances = 0

        def __init__(self):
            type(self).instances += 1
            super().__init__()

    monkeypatch.setattr(deps.settings, "retriever", "hybrid")
    monkeypatch.setattr(deps, "ensure_fts", lambda _engine: True)
    monkeypatch.setattr(deps, "ensure_vec", lambda _engine: True)
    monkeypatch.setattr(onnx_embedder, "OnnxEmbedder", CountingEmbedder)
    deps.reset_retriever_cache()

    first = deps.get_retriever()
    second = deps.get_retriever()

    assert isinstance(first, HybridRetriever)
    assert isinstance(second, HybridRetriever)
    assert first.embedder is second.embedder
    assert CountingEmbedder.instances == 1
    deps.reset_retriever_cache()


def test_get_embedder_uses_scripted_backend_for_scripted_retrieval(monkeypatch):
    from adaptive_academy.api import deps

    monkeypatch.setattr(deps.settings, "retriever", "scripted")

    assert isinstance(deps.get_embedder(), ScriptedEmbedder)


def test_memory_stats_reports_active_hybrid_retriever(vec_session):
    retriever = HybridRetriever(FtsRetriever(), ScriptedEmbedder())

    hybrid_stats = memory_stats(session=vec_session, retriever=retriever)
    fts_stats = memory_stats(session=vec_session, retriever=FtsRetriever())

    assert hybrid_stats.retriever == "hybrid"
    assert fts_stats.retriever == "fts"


def test_ensure_vec_degrades_without_enable_load_extension(monkeypatch):
    from adaptive_academy import db

    engine = create_engine("sqlite://")

    def missing_enable_load_extension(_connection, _):
        raise AttributeError("enable_load_extension")

    monkeypatch.setattr(db, "_load_vec_extension", missing_enable_load_extension)

    assert db.ensure_vec(engine) is False


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


def test_hybrid_warmup_failure_is_cached_as_fts(monkeypatch):
    from adaptive_academy.api import deps

    class FailingWarmupEmbedder(ScriptedEmbedder):
        calls = 0

        def embed(self, texts):
            type(self).calls += 1
            raise RuntimeError("cannot load local model")

    embedder = FailingWarmupEmbedder()
    monkeypatch.setattr(deps.settings, "retriever", "hybrid")
    monkeypatch.setattr(deps, "ensure_fts", lambda _engine: True)
    monkeypatch.setattr(deps, "ensure_vec", lambda _engine: True)
    monkeypatch.setattr(deps, "get_embedder", lambda: embedder)
    deps.reset_retriever_cache()

    first = deps.get_retriever()
    second = deps.get_retriever()

    assert isinstance(first, FtsRetriever)
    assert isinstance(second, FtsRetriever)
    assert embedder.calls == 1
    deps.reset_retriever_cache()


def test_hybrid_degrades_once_when_downloads_disabled_and_model_not_cached(
    monkeypatch,
    caplog,
    tmp_path,
):
    from adaptive_academy.api import deps

    monkeypatch.setattr(deps.settings, "retriever", "hybrid")
    monkeypatch.setattr(deps.settings, "embedding_allow_download", False)
    monkeypatch.setattr(deps.settings, "embedding_cache_dir", str(tmp_path))
    (tmp_path / "models--BAAI--bge-small-en-v1.5").mkdir()
    monkeypatch.setattr(deps, "ensure_fts", lambda _engine: True)
    monkeypatch.setattr(deps, "ensure_vec", lambda _engine: True)
    monkeypatch.setattr(deps, "_logged_retriever_degradations", set())
    deps.reset_retriever_cache()

    with caplog.at_level("WARNING"):
        first = deps.get_retriever()
        second = deps.get_retriever()

    assert isinstance(first, FtsRetriever)
    assert isinstance(second, FtsRetriever)
    assert caplog.messages.count("Hybrid retrieval is unavailable; using FTS5.") == 1
    deps.reset_retriever_cache()


def test_model_cache_requires_onnx_file_under_matching_directory(tmp_path):
    model_dir = tmp_path / "models--BAAI--bge-small-en-v1.5"
    model_dir.mkdir()

    assert not _model_is_cached("BAAI/bge-small-en-v1.5", str(tmp_path))

    snapshot = model_dir / "snapshots" / "revision"
    snapshot.mkdir(parents=True)
    (snapshot / "model.onnx").write_bytes(b"dummy")

    assert _model_is_cached("BAAI/bge-small-en-v1.5", str(tmp_path))


def test_onnx_embedder_uses_fake_cached_model_when_downloads_disabled(
    monkeypatch,
    tmp_path,
):
    from adaptive_academy.llm import onnx_embedder

    cache_dir = tmp_path / "fastembed_cache"
    model_dir = cache_dir / "models--BAAI--bge-small-en-v1.5"
    model_dir.mkdir(parents=True)
    (model_dir / "model.onnx").write_bytes(b"dummy")
    calls = []

    class FakeVector:
        def tolist(self):
            return [0.0] * 384

    class RecordingTextEmbedding:
        def __init__(self, *, model_name, cache_dir, lazy_load, local_files_only=None):
            assert local_files_only is True  # downloads disabled -> offline-only load
            calls.append((model_name, cache_dir, lazy_load))

        def embed(self, texts):
            return [FakeVector() for _ in texts]

    monkeypatch.setattr(onnx_embedder, "TextEmbedding", RecordingTextEmbedding)
    monkeypatch.setattr(onnx_embedder.settings, "embedding_allow_download", False)
    monkeypatch.setattr(onnx_embedder.settings, "embedding_cache_dir", str(cache_dir))

    embedder = OnnxEmbedder()
    embedder.embed(["cached text"])

    assert calls == [
        ("BAAI/bge-small-en-v1.5", str(cache_dir), True),
    ]


def test_hybrid_degrades_once_when_embedding_dimensions_mismatch(monkeypatch, caplog):
    from adaptive_academy.api import deps

    monkeypatch.setattr(deps.settings, "retriever", "hybrid")
    monkeypatch.setattr(deps, "ensure_fts", lambda _engine: True)
    monkeypatch.setattr(deps, "ensure_vec", lambda _engine: True)
    monkeypatch.setattr(deps, "get_embedder", lambda: ScriptedEmbedder(dim=3))
    monkeypatch.setattr(deps, "_logged_retriever_degradations", set())
    deps.reset_retriever_cache()

    with caplog.at_level("WARNING"):
        first = deps.get_retriever()
        second = deps.get_retriever()

    assert isinstance(first, FtsRetriever)
    assert isinstance(second, FtsRetriever)
    assert caplog.messages.count("Hybrid retrieval is unavailable; using FTS5.") == 1
    deps.reset_retriever_cache()


def test_offline_mode_passes_local_files_only_to_fastembed(monkeypatch, tmp_path):
    from adaptive_academy.llm import onnx_embedder

    captured: dict = {}

    class FakeModel:
        def __init__(self, **kwargs):
            captured.update(kwargs)

        def embed(self, texts):
            import numpy as np

            return [np.zeros(384, dtype="float32") for _ in texts]

    monkeypatch.setattr(onnx_embedder, "TextEmbedding", FakeModel)
    monkeypatch.setattr(onnx_embedder.settings, "embedding_allow_download", False)
    monkeypatch.setattr(onnx_embedder, "_model_is_cached", lambda *_a, **_k: True)
    embedder = onnx_embedder.OnnxEmbedder()
    embedder.embed(["x"])
    assert captured.get("local_files_only") is True


def test_vector_leg_ignores_vectors_from_another_model(session):
    """Vectors written by model A are never ranked when the active embedder is model B."""
    from adaptive_academy.engine.memory import ChunkFilter
    from adaptive_academy.llm.hybrid_retriever import _eligible_chunk_ids
    from adaptive_academy.models import Chunk

    a = Chunk(kind="vault_note", source_ref="file:///v/a.md", ordinal=0, heading="",
              text="alpha", content_hash="ha", embedding_model="model-a")
    b = Chunk(kind="vault_note", source_ref="file:///v/b.md", ordinal=0, heading="",
              text="beta", content_hash="hb", embedding_model="model-b")
    session.add(a)
    session.add(b)
    session.commit()
    where = ChunkFilter(kinds=("vault_note",))
    assert _eligible_chunk_ids(session, where, embedding_model="model-b") == [b.id]
    assert set(_eligible_chunk_ids(session, where)) == {a.id, b.id}
