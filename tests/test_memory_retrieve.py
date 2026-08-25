from datetime import datetime, timedelta, timezone

from sqlmodel import select

from adaptive_academy.engine.memory import (
    ChunkFilter,
    content_hash,
    expand_query,
    retrieve,
)
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
from adaptive_academy.models import (
    AgentEvent,
    Chunk,
    Concept,
    ConceptAlias,
    Program,
    Topic,
    Track,
    VaultLink,
)
from adaptive_academy.settings import Settings


def _chunk(
    text_value: str,
    source_ref: str,
    *,
    ordinal: int = 0,
    kind: str = "vault_note",
    topic_id: int | None = None,
    concept_id: int | None = None,
    created_at: datetime | None = None,
) -> Chunk:
    values = {}
    if created_at is not None:
        values["created_at"] = created_at
    return Chunk(
        kind=kind,
        topic_id=topic_id,
        concept_id=concept_id,
        source_ref=source_ref,
        ordinal=ordinal,
        text=text_value,
        content_hash=content_hash(text_value),
        **values,
    )


def test_retrieve_deduplicates_caps_and_emits_targeted_event(session):
    topic = Topic(title="Memory")
    session.add(topic)
    session.flush()
    first = _chunk("same text", "vault:first", topic_id=topic.id)
    duplicate = _chunk("same text", "vault:duplicate", topic_id=topic.id)
    distinct = _chunk("different text", "vault:distinct", topic_id=topic.id)
    session.add_all([first, duplicate, distinct])
    session.flush()
    retriever = ScriptedRetriever({"memory": [first.id, duplicate.id, distinct.id]})

    hits = retrieve(
        session,
        retriever,
        "memory",
        topic_id=topic.id,
        k=3,
        event_target={"topic_id": topic.id},
    )

    assert [hit.chunk.id for hit in hits] == [first.id, distinct.id]
    event = session.exec(
        select(AgentEvent).where(AgentEvent.kind == "memory:retrieve")
    ).one()
    assert event.topic_id == topic.id
    assert "k=3 hits=2 links=0" in event.detail


def test_retrieve_caps_three_distinct_candidates_to_one(session):
    chunks = [
        _chunk(f"distinct {index}", f"vault:{index}")
        for index in range(3)
    ]
    session.add_all(chunks)
    session.flush()
    retriever = ScriptedRetriever(
        {"memory": [chunk.id for chunk in chunks if chunk.id is not None]}
    )

    hits = retrieve(session, retriever, "memory", k=1)

    assert len(hits) == 1
    assert hits[0].chunk.id == chunks[0].id


def test_retrieve_overfetches_before_deduplicating(session):
    first = _chunk("same text", "vault:first")
    duplicate = _chunk("same text", "vault:duplicate")
    distinct = _chunk("different text", "vault:distinct")
    session.add_all([first, duplicate, distinct])
    session.flush()
    retriever = ScriptedRetriever({"memory": [first.id, duplicate.id, distinct.id]})

    hits = retrieve(session, retriever, "memory", k=2)

    assert [hit.chunk.id for hit in hits] == [first.id, distinct.id]


def test_retrieve_converts_backend_failure_to_error_event(session):
    topic = Topic(title="Errors")
    session.add(topic)
    session.flush()

    class RaisingRetriever:
        name = "raising"

        def search(self, session, query, *, where, k):
            raise RuntimeError("boom")

        def on_index(self, session, chunk_ids):
            return None

    hits = retrieve(
        session,
        RaisingRetriever(),
        "memory",
        event_target={"topic_id": topic.id},
    )

    assert hits == []
    event = session.exec(select(AgentEvent).where(AgentEvent.kind == "memory:error")).one()
    assert event.topic_id == topic.id
    assert "RuntimeError: boom" in event.detail


def test_scripted_retriever_honors_where(session):
    topic = Topic(title="Filters")
    session.add(topic)
    session.flush()
    track = Track(topic_id=topic.id, title="Track")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="Concept")
    other_concept = Concept(track_id=track.id, name="Other")
    session.add_all([concept, other_concept])
    session.flush()

    exact = _chunk("memory exact", "exact", topic_id=topic.id, concept_id=concept.id)
    topic_wide = _chunk("memory topic", "topic", topic_id=topic.id)
    wrong = _chunk(
        "memory wrong",
        "wrong",
        topic_id=topic.id,
        concept_id=other_concept.id,
    )
    session.add_all([exact, topic_wide, wrong])
    session.flush()

    retriever = ScriptedRetriever({"memory": [wrong.id, topic_wide.id, exact.id]})
    hits = retriever.search(
        session,
        "memory",
        where=ChunkFilter(
            kinds=("vault_note",),
            topic_id=topic.id,
            concept_id=concept.id,
            exclude_source_refs=("exact",),
        ),
        k=10,
    )

    assert [chunk_id for chunk_id, _ in hits] == [topic_wide.id]

    retriever.hits["memory Concept"] = [wrong.id, topic_wide.id, exact.id]
    concept_only_hits = retrieve(
        session,
        retriever,
        "memory",
        concept_id=concept.id,
        k=10,
    )

    assert [hit.chunk.id for hit in concept_only_hits] == [topic_wide.id, exact.id]


def test_retrieve_recency_and_since(session):
    topic = Topic(title="Recency")
    session.add(topic)
    session.flush()
    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    old = _chunk("old", "old", topic_id=topic.id, created_at=now - timedelta(days=3))
    middle = _chunk(
        "middle",
        "middle",
        topic_id=topic.id,
        created_at=now - timedelta(hours=2),
    )
    newest = _chunk("newest", "newest", topic_id=topic.id, created_at=now)
    session.add_all([old, middle, newest])
    session.flush()
    retriever = ScriptedRetriever({"history": [old.id, middle.id, newest.id]})

    hits = retrieve(
        session,
        retriever,
        "history",
        topic_id=topic.id,
        k=2,
        order="recency",
        since=now - timedelta(days=1),
        event_target={"topic_id": topic.id},
    )

    assert [hit.chunk.id for hit in hits] == [newest.id, middle.id]


def test_expand_query_appends_concept_name_and_alias(session):
    topic = Topic(title="Aliases")
    program = Program(title="Program")
    session.add_all([topic, program])
    session.flush()
    track = Track(topic_id=topic.id, title="Track")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="Attention")
    session.add(concept)
    session.flush()
    session.add(
        ConceptAlias(
            program_id=program.id,
            concept_id=concept.id,
            canonical_name="Self Attention",
        )
    )
    session.flush()

    expanded = expand_query(session, "transformers", concept_id=concept.id)

    assert expanded == "transformers Attention Self Attention"


def test_expand_links_adds_best_neighbor_below_direct_hits(session):
    source = _chunk("memory source", "vault:a")
    linked_best = _chunk("memory linked best", "vault:b")
    linked_other = _chunk("memory linked other", "vault:b", ordinal=1)
    session.add_all([source, linked_best, linked_other])
    session.flush()
    session.add(VaultLink(src_ref="vault:a", dst_ref="vault:b", dst_title="B"))
    session.flush()
    class LinkAwareRetriever:
        name = "link-aware"

        def search(self, session, query, *, where, k):
            if where.source_refs:
                return [(linked_other.id, 0.2), (linked_best.id, 0.8)][:k]
            return [(source.id, 1.0)][:k]

        def on_index(self, session, chunk_ids):
            return None

    hits = retrieve(
        session,
        LinkAwareRetriever(),
        "memory",
        k=2,
        expand_links=True,
    )

    assert [hit.chunk.id for hit in hits] == [source.id, linked_best.id]
    assert [hit.via for hit in hits] == ["direct", "link"]
    assert [hit.score for hit in hits] == [1.0, 0.0]


def test_expand_links_preserves_neighbors_already_ranked_as_direct(session):
    source = _chunk("memory source", "vault:a")
    neighbor = _chunk("memory neighbor", "vault:b")
    session.add_all([source, neighbor])
    session.flush()
    session.add(VaultLink(src_ref="vault:a", dst_ref="vault:b", dst_title="B"))
    session.flush()
    retriever = ScriptedRetriever({"memory": [source.id, neighbor.id]})

    direct = retrieve(session, retriever, "memory", k=3)
    expanded = retrieve(session, retriever, "memory", k=3, expand_links=True)

    assert [(hit.chunk.id, hit.score, hit.via) for hit in expanded] == [
        (hit.chunk.id, hit.score, hit.via) for hit in direct
    ]


def test_expand_links_uses_ordinal_zero_when_neighbor_does_not_match(session):
    source = _chunk("memory alpha", "vault:a")
    neighbor = _chunk("totally unrelated words", "vault:b")
    session.add_all([source, neighbor])
    session.flush()
    session.add(VaultLink(src_ref="vault:a", dst_ref="vault:b", dst_title="B"))
    session.flush()

    hits = retrieve(
        session,
        FtsRetriever(),
        "memory",
        k=3,
        expand_links=True,
    )

    assert [hit.chunk.id for hit in hits] == [source.id, neighbor.id]
    assert [hit.via for hit in hits] == ["direct", "link"]
    assert hits[1].chunk.ordinal == 0
    assert hits[1].score == 0.0


def test_retriever_setting_uses_aa_environment(monkeypatch):
    from adaptive_academy.api import deps

    monkeypatch.setenv("AA_RETRIEVER", "scripted")
    configured = Settings(_env_file=None)
    monkeypatch.setattr(deps, "settings", configured)

    def fail_if_called(_engine):
        raise AssertionError("scripted retrieval must not inspect the engine")

    monkeypatch.setattr(deps, "ensure_fts", fail_if_called)

    assert configured.retriever == "scripted"
    assert isinstance(deps.get_retriever(), ScriptedRetriever)


def test_get_retriever_accepts_vec_as_hybrid_alias(monkeypatch):
    from adaptive_academy.api import deps

    monkeypatch.setattr(deps.settings, "retriever", "vec")
    monkeypatch.setattr(deps, "ensure_fts", lambda _engine: True)
    deps.reset_retriever_cache()

    assert isinstance(deps.get_retriever(), FtsRetriever)


def test_get_retriever_warns_once_and_uses_fts_for_unknown_value(
    monkeypatch,
    caplog,
):
    from adaptive_academy.api import deps

    monkeypatch.setattr(deps.settings, "retriever", "unknown")
    monkeypatch.setattr(deps, "ensure_fts", lambda _engine: True)
    monkeypatch.setattr(deps, "_logged_retriever_degradations", set())
    deps.reset_retriever_cache()

    with caplog.at_level("WARNING"):
        first = deps.get_retriever()
        second = deps.get_retriever()

    assert isinstance(first, FtsRetriever)
    assert isinstance(second, FtsRetriever)
    assert caplog.messages.count("Unsupported retriever 'unknown'; using FTS5.") == 1


def test_get_retriever_degrades_to_scripted_without_fts(monkeypatch):
    from adaptive_academy.api import deps

    monkeypatch.setattr(deps.settings, "retriever", "fts")
    calls = 0

    def unavailable(_engine):
        nonlocal calls
        calls += 1
        return False

    monkeypatch.setattr(deps, "ensure_fts", unavailable)
    deps.reset_retriever_cache()

    assert isinstance(deps.get_retriever(), ScriptedRetriever)
    assert isinstance(deps.get_retriever(), ScriptedRetriever)
    assert calls == 1
    deps.reset_retriever_cache()
