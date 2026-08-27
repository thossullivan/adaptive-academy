import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from adaptive_academy.api import routes_memory
from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_fetcher, get_retriever, get_session
from adaptive_academy.engine.memory import index_text
from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
from adaptive_academy.models import Chunk, SourceDoc, Topic


@pytest.fixture
def memory_api(session):
    topic = Topic(title="Memory API")
    session.add(topic)
    session.commit()
    session.refresh(topic)

    retriever = ScriptedRetriever({})
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_retriever] = lambda: retriever
    app.dependency_overrides[get_fetcher] = lambda: (
        lambda url: f"Fetched source text for {url}."
    )
    client = TestClient(app)
    yield client, topic, retriever
    app.dependency_overrides.clear()


def test_search_returns_ranked_hits_with_bounded_snippets_and_rejects_blank_query(
    session,
    memory_api,
):
    client, topic, retriever = memory_api
    index_text(
        session,
        kind="vault_note",
        text="Attention first.\n\n" + "bounded snippet text " * 20,
        source_ref="file:///vault/attention.md",
        doc_title="Attention",
        topic_id=topic.id,
        heading="Mechanism",
    )
    index_text(
        session,
        kind="source_doc",
        text="Attention second.",
        source_ref="sourcedoc:1",
        topic_id=topic.id,
        heading="Paper",
    )
    session.commit()
    chunks = session.exec(select(Chunk).order_by(Chunk.id)).all()
    retriever.hits["attention"] = [chunks[1].id, chunks[0].id]

    response = client.get(
        "/api/memory/search",
        params={
            "q": "attention",
            "topic_id": topic.id,
            "kinds": "vault_note,source_doc",
            "k": 2,
        },
    )

    assert response.status_code == 200
    hits = response.json()["hits"]
    assert [hit["chunk_id"] for hit in hits] == [chunks[1].id, chunks[0].id]
    assert hits[0] == {
        "chunk_id": chunks[1].id,
        "kind": "source_doc",
        "heading": "Paper",
        "snippet": "Attention second.",
        "score": 1.0,
        "source_ref": "sourcedoc:1",
    }
    assert len(hits[1]["snippet"]) <= 240
    assert "\n" not in hits[1]["snippet"]
    assert client.get("/api/memory/search", params={"q": "   "}).status_code == 400
    assert client.get("/api/memory/search").status_code == 400
    assert (
        client.get("/api/memory/search", params={"q": "attention", "k": 51}).status_code
        == 422
    )


def test_reindex_tmp_vault_is_idempotent(session, memory_api, tmp_path):
    client, topic, _ = memory_api
    (tmp_path / "note.md").write_text(
        "# Retrieval\n\nStable local memory.",
        encoding="utf-8",
    )

    first = client.post(
        "/api/memory/reindex",
        json={"topic_id": topic.id, "vault_path": str(tmp_path)},
    )
    second = client.post(
        "/api/memory/reindex",
        json={"topic_id": topic.id, "vault_path": str(tmp_path)},
    )

    assert first.status_code == second.status_code == 200
    assert first.json()["indexed"] == 1
    assert first.json()["skipped"] == first.json()["removed"] == 0
    assert first.json()["truncated"] is False
    assert first.json()["ms"] >= 0
    assert second.json()["indexed"] == second.json()["removed"] == 0
    assert second.json()["skipped"] == 1


def test_reindex_without_topic_indexes_all_topics(session, memory_api):
    client, first_topic, _ = memory_api
    second_topic = Topic(title="Second topic")
    session.add(second_topic)
    session.commit()
    session.refresh(second_topic)
    session.add_all(
        [
            SourceDoc(
                topic_id=first_topic.id,
                title="First",
                url="https://example.test/first",
                status="accepted",
            ),
            SourceDoc(
                topic_id=second_topic.id,
                title="Second",
                url="https://example.test/second",
                status="accepted",
            ),
        ]
    )
    session.commit()

    response = client.post(
        "/api/memory/reindex",
        json={"kinds": ["source_doc"]},
    )

    assert response.status_code == 200
    assert response.json()["indexed"] == 2
    chunks = session.exec(select(Chunk).where(Chunk.kind == "source_doc")).all()
    assert {chunk.topic_id for chunk in chunks} == {first_topic.id, second_topic.id}


def test_reindex_without_topic_preserves_vault_chunk_owners(
    session,
    memory_api,
    tmp_path,
):
    client, first_topic, _ = memory_api
    second_topic = Topic(title="Second topic")
    session.add(second_topic)
    session.commit()
    session.refresh(second_topic)
    (tmp_path / "a.md").write_text("# Alpha\n\nFirst note.", encoding="utf-8")
    seeded = client.post(
        "/api/memory/reindex",
        json={
            "topic_id": first_topic.id,
            "vault_path": str(tmp_path),
            "kinds": ["vault_note"],
        },
    )
    assert seeded.status_code == 200
    # b.md belongs to the second topic only (indexed directly, not via a sweep).
    b_path = tmp_path / "b.md"
    b_path.write_text("# Beta\n\nSecond note.", encoding="utf-8")
    index_text(
        session,
        kind="vault_note",
        text=b_path.read_text(encoding="utf-8"),
        source_ref=b_path.resolve().as_uri(),
        doc_title="Beta",
        topic_id=second_topic.id,
        source_mtime=b_path.stat().st_mtime,
    )
    session.commit()
    before = {
        chunk.source_ref: chunk.topic_id
        for chunk in session.exec(
            select(Chunk).where(Chunk.kind == "vault_note").order_by(Chunk.source_ref)
        ).all()
    }
    assert len(before) == 2
    assert set(before.values()) == {first_topic.id, second_topic.id}

    response = client.post(
        "/api/memory/reindex",
        json={"vault_path": str(tmp_path)},
    )

    assert response.status_code == 200
    after = {
        chunk.source_ref: chunk.topic_id
        for chunk in session.exec(
            select(Chunk).where(Chunk.kind == "vault_note").order_by(Chunk.source_ref)
        ).all()
    }
    assert after == before


def test_reindex_rejects_unsupported_kinds(memory_api):
    client, _, _ = memory_api

    response = client.post(
        "/api/memory/reindex",
        json={"kinds": ["bogus"]},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "unsupported reindex kinds: bogus"


def test_reindex_reports_truncation_when_deadline_is_exhausted(
    memory_api,
    monkeypatch,
):
    client, _, _ = memory_api
    monkeypatch.setattr(routes_memory, "REINDEX_DEADLINE_S", 0.0)

    response = client.post(
        "/api/memory/reindex",
        json={"kinds": ["source_doc"]},
    )

    assert response.status_code == 200
    assert response.json()["truncated"] is True


def test_reindex_returns_409_while_another_reindex_holds_lock(memory_api):
    client, topic, _ = memory_api
    assert routes_memory._reindex_lock.acquire(timeout=0.1)
    try:
        response = client.post(
            "/api/memory/reindex",
            json={"topic_id": topic.id, "kinds": ["source_doc"]},
        )
    finally:
        routes_memory._reindex_lock.release()

    assert response.status_code == 409
    assert response.json() == {"detail": "reindex already running"}


def test_reindex_integrity_error_returns_409_with_partial_counts(
    memory_api,
    monkeypatch,
):
    client, topic, _ = memory_api

    def fail_reindex(*_args, **_kwargs):
        raise IntegrityError("reindex", {}, RuntimeError("collision"))

    monkeypatch.setattr(routes_memory, "reindex_topic", fail_reindex)

    response = client.post(
        "/api/memory/reindex",
        json={"topic_id": topic.id, "kinds": ["source_doc"]},
    )

    assert response.status_code == 409
    body = response.json()
    assert body["indexed"] == body["skipped"] == body["removed"] == 0
    assert "partial counts" in body["note"]


def test_stats_counts_match_topic(session, memory_api):
    client, topic, _ = memory_api
    other_topic = Topic(title="Other")
    session.add(other_topic)
    session.commit()
    session.refresh(other_topic)
    index_text(
        session,
        kind="vault_note",
        text="One",
        source_ref="file:///vault/one.md",
        topic_id=topic.id,
    )
    index_text(
        session,
        kind="vault_note",
        text="Two",
        source_ref="file:///vault/two.md",
        topic_id=topic.id,
    )
    index_text(
        session,
        kind="question",
        text="Three",
        source_ref="question:three",
        topic_id=topic.id,
    )
    index_text(
        session,
        kind="source_doc",
        text="Other",
        source_ref="sourcedoc:other",
        topic_id=other_topic.id,
    )
    session.commit()

    response = client.get("/api/memory/stats", params={"topic_id": topic.id})

    assert response.status_code == 200
    assert response.json()["by_kind"] == {"question": 1, "vault_note": 2}
    assert response.json()["last_indexed_at"] is not None
    assert response.json()["retriever"] == "scripted"


def test_reindex_without_topic_on_fresh_db_reports_note(memory_api, tmp_path):
    client, _, _ = memory_api
    (tmp_path / "a.md").write_text("# Alpha\n\nFirst note.", encoding="utf-8")
    response = client.post("/api/memory/reindex", json={"vault_path": str(tmp_path)})
    assert response.status_code == 200
    body = response.json()
    assert body["indexed"] == 0
    assert "pass topic_id" in body["note"]


def test_search_unknown_topic_or_concept_is_404(memory_api):
    client, _, _ = memory_api
    assert client.get("/api/memory/search", params={"q": "x", "topic_id": 99999}).status_code == 404
    assert client.get("/api/memory/search", params={"q": "x", "concept_id": 99999}).status_code == 404


def test_reindex_operational_error_before_topic_work_returns_409(memory_api, monkeypatch):
    from sqlalchemy.exc import OperationalError

    client, topic, _ = memory_api

    def locked_exec(*_args, **_kwargs):
        raise OperationalError("select", {}, RuntimeError("database is locked"))

    # The very first DB call of the handler (topic lookup) fails; still 409, never 500.
    monkeypatch.setattr(routes_memory.Session, "exec", locked_exec)
    response = client.post(
        "/api/memory/reindex", json={"topic_id": topic.id, "kinds": ["source_doc"]}
    )
    assert response.status_code == 409
    assert "partial counts" in response.json()["note"]


def test_reindex_conflict_after_committed_files_reports_partial_counts(memory_api, monkeypatch):
    client, topic, _ = memory_api

    def two_files_then_conflict(*_args, progress=None, **_kwargs):
        progress["indexed"] += 2
        progress["skipped"] += 1
        raise IntegrityError("reindex", {}, RuntimeError("collision"))

    monkeypatch.setattr(routes_memory, "reindex_topic", two_files_then_conflict)
    response = client.post(
        "/api/memory/reindex", json={"topic_id": topic.id, "kinds": ["source_doc"]}
    )
    assert response.status_code == 409
    body = response.json()
    assert body["indexed"] == 2
    assert body["skipped"] == 1
    assert body["truncated"] is True


def test_vault_ingest_returns_409_while_reindex_lock_is_held(memory_api, tmp_path):
    from adaptive_academy.engine.memory import REINDEX_LOCK

    client, topic, _ = memory_api
    (tmp_path / "a.md").write_text("# A\n\nnote", encoding="utf-8")
    assert REINDEX_LOCK.acquire(timeout=0.1)
    try:
        response = client.post(
            f"/api/topics/{topic.id}/vault/ingest", json={"vault_path": str(tmp_path)}
        )
    finally:
        REINDEX_LOCK.release()
    assert response.status_code == 409


def test_search_rejects_concept_from_another_topic(session, memory_api):
    from adaptive_academy.models import Concept, Track

    client, topic, _ = memory_api
    other = Topic(title="Other")
    session.add(other)
    session.commit()
    track = Track(topic_id=other.id, title="Other")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="Foreign")
    session.add(concept)
    session.commit()
    mismatched = client.get(
        "/api/memory/search", params={"q": "x", "topic_id": topic.id, "concept_id": concept.id}
    )
    matched = client.get(
        "/api/memory/search", params={"q": "x", "topic_id": other.id, "concept_id": concept.id}
    )
    assert mismatched.status_code == 400
    assert matched.status_code == 200


def test_all_topic_reindex_checks_deadline_before_any_topic_work(memory_api, monkeypatch, tmp_path):
    calls = {"n": 0}

    def never(*_a, **_k):
        calls["n"] += 1
        raise AssertionError("reindex_topic must not run after the deadline")

    monkeypatch.setattr(routes_memory, "reindex_topic", never)
    monkeypatch.setattr(routes_memory, "REINDEX_DEADLINE_S", 0.0)
    client, _topic, _ = memory_api
    (tmp_path / "a.md").write_text("# A\n\nbody", encoding="utf-8")
    response = client.post("/api/memory/reindex", json={"vault_path": str(tmp_path)})
    assert response.status_code == 200
    assert response.json()["truncated"] is True
    assert calls["n"] == 0


def test_owned_vault_refs_are_enumerated_in_deadline_checked_batches(session, memory_api, monkeypatch):
    import time

    from adaptive_academy.api import routes_memory as rm

    client, topic, _ = memory_api
    for i in range(5):
        index_text(session, kind="vault_note", text=f"n{i}", topic_id=topic.id,
                   source_ref=f"file:///v/n{i}.md")
    session.commit()
    monkeypatch.setattr(rm, "REINDEX_TOPIC_BATCH", 2)
    refs, complete = rm._owned_vault_refs(session, topic.id, time.perf_counter() + 60)
    assert complete is True and len(refs) == 5
    refs, complete = rm._owned_vault_refs(session, topic.id, time.perf_counter() - 1)
    assert complete is False and refs == set()
