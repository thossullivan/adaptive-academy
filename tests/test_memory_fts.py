from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from adaptive_academy.engine.memory import ChunkFilter, content_hash, sanitize_fts_query
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.models import Chunk, Concept, Topic, Track


def _chunk(
    text_value: str,
    source_ref: str,
    *,
    kind: str = "vault_note",
    topic_id: int | None = None,
    concept_id: int | None = None,
    context: str = "",
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
        text=text_value,
        context=context,
        content_hash=content_hash(text_value),
        **values,
    )


def test_fts_triggers_keep_insert_update_delete_in_sync(session):
    chunk = _chunk("initial comet", "vault:a", context="Astronomy")
    session.add(chunk)
    session.flush()

    assert session.execute(
        text("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH :query"),
        {"query": "initial"},
    ).scalars().all() == [chunk.id]

    chunk.text = "revised nebula"
    chunk.context = "Deep Space"
    session.add(chunk)
    session.flush()

    assert session.execute(
        text("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH :query"),
        {"query": "initial"},
    ).scalars().all() == []
    assert session.execute(
        text("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH :query"),
        {"query": "space"},
    ).scalars().all() == [chunk.id]

    session.delete(chunk)
    session.flush()
    assert session.execute(
        text("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH :query"),
        {"query": "nebula"},
    ).scalars().all() == []


def test_fts_bm25_prefers_exact_frequency_and_searches_context(session):
    exact = _chunk("quasar quasar quasar", "vault:exact")
    weak = _chunk("a quasar appears once among many unrelated words", "vault:weak")
    contextual = _chunk("body without the term", "vault:context", context="Quasar Guide")
    session.add_all([weak, exact, contextual])
    session.flush()

    hits = FtsRetriever().search(session, "quasar", where=ChunkFilter(), k=3)

    assert hits[0][0] == exact.id
    assert contextual.id in [chunk_id for chunk_id, _ in hits]
    assert all(0.0 <= score <= 1.0 for _, score in hits)


def test_sanitizer_makes_hostile_input_a_valid_match(session):
    foo = _chunk("foo only", "vault:foo")
    other = _chunk("unrelated content", "vault:other")
    session.add_all([foo, other])
    session.flush()

    sanitized = sanitize_fts_query('foo" OR 1=1 --')
    hits = FtsRetriever().search(
        session,
        'foo" OR 1=1 --',
        where=ChunkFilter(),
        k=10,
    )

    assert sanitized == '"foo" OR "OR"'
    assert [chunk_id for chunk_id, _ in hits] == [foo.id]
    assert FtsRetriever().search(session, "- !", where=ChunkFilter(), k=10) == []


def test_fts_applies_all_filters_before_ranking(session):
    topic_one = Topic(title="One")
    topic_two = Topic(title="Two")
    session.add_all([topic_one, topic_two])
    session.flush()
    track_one = Track(topic_id=topic_one.id, title="One")
    track_two = Track(topic_id=topic_two.id, title="Two")
    session.add_all([track_one, track_two])
    session.flush()
    concept_one = Concept(track_id=track_one.id, name="One")
    concept_other = Concept(track_id=track_one.id, name="Other")
    session.add_all([concept_one, concept_other])
    session.flush()

    now = datetime(2026, 8, 25, tzinfo=timezone.utc)
    exact = _chunk(
        "retrieval",
        "source:exact",
        kind="source_doc",
        topic_id=topic_one.id,
        concept_id=concept_one.id,
        created_at=now - timedelta(days=2),
    )
    topic_wide = _chunk(
        "retrieval",
        "vault:topic",
        topic_id=topic_one.id,
        created_at=now,
    )
    learner = _chunk(
        "retrieval",
        "learner:one",
        kind="learner_output",
        topic_id=topic_one.id,
        concept_id=concept_one.id,
        created_at=now,
    )
    wrong_concept = _chunk(
        "retrieval",
        "vault:wrong-concept",
        topic_id=topic_one.id,
        concept_id=concept_other.id,
        created_at=now,
    )
    wrong_topic = _chunk(
        "retrieval",
        "vault:wrong-topic",
        topic_id=topic_two.id,
        created_at=now,
    )
    session.add_all([exact, topic_wide, learner, wrong_concept, wrong_topic])
    session.flush()
    retriever = FtsRetriever()

    concept_hits = retriever.search(
        session,
        "retrieval",
        where=ChunkFilter(topic_id=topic_one.id, concept_id=concept_one.id),
        k=10,
    )
    assert {chunk_id for chunk_id, _ in concept_hits} == {
        exact.id,
        topic_wide.id,
        learner.id,
    }

    vault_hits = retriever.search(
        session,
        "retrieval",
        where=ChunkFilter(
            kinds=("vault_note",),
            topic_id=topic_one.id,
            concept_id=concept_one.id,
        ),
        k=10,
    )
    assert [chunk_id for chunk_id, _ in vault_hits] == [topic_wide.id]

    excluded = retriever.search(
        session,
        "retrieval",
        where=ChunkFilter(
            topic_id=topic_one.id,
            concept_id=concept_one.id,
            exclude_source_refs=("vault:topic",),
            since=now - timedelta(days=1),
        ),
        k=10,
    )
    assert [chunk_id for chunk_id, _ in excluded] == [learner.id]

    other_topic_hits = retriever.search(
        session,
        "retrieval",
        where=ChunkFilter(topic_id=topic_two.id),
        k=10,
    )
    assert [chunk_id for chunk_id, _ in other_topic_hits] == [wrong_topic.id]
