import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

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
