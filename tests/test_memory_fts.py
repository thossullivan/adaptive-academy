from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from adaptive_academy.engine.memory import ChunkFilter, content_hash, sanitize_fts_query
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.llm.scripted_retriever import ScriptedRetriever
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
    operator = _chunk("or", "vault:operator")
    other = _chunk("unrelated content", "vault:other")
    session.add_all([foo, operator, other])
    session.flush()

    sanitized = sanitize_fts_query('foo" OR 1=1 --')
    hits = FtsRetriever().search(
        session,
        'foo" OR 1=1 --',
        where=ChunkFilter(),
        k=10,
    )

    assert sanitized == '"foo"'
    assert [chunk_id for chunk_id, _ in hits] == [foo.id]
    assert operator.id not in [chunk_id for chunk_id, _ in hits]
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


def test_retrievers_include_exact_since_and_derive_topic_from_concept(session):
    topic = Topic(title="Concept topic")
    other_topic = Topic(title="Other topic")
    session.add_all([topic, other_topic])
    session.flush()
    track = Track(topic_id=topic.id, title="Track")
    session.add(track)
    session.flush()
    concept = Concept(track_id=track.id, name="Concept")
    session.add(concept)
    session.flush()

    since = datetime(2026, 8, 24, 12, 0, 0, 500000, tzinfo=timezone.utc)
    exact = _chunk(
        "retrieval",
        "source:exact-since",
        topic_id=topic.id,
        concept_id=concept.id,
        created_at=since,
    )
    topic_wide = _chunk(
        "retrieval",
        "vault:topic-wide",
        topic_id=topic.id,
        created_at=since,
    )
    too_old = _chunk(
        "retrieval",
        "vault:too-old",
        topic_id=topic.id,
        created_at=since - timedelta(microseconds=1),
    )
    wrong_topic = _chunk(
        "retrieval",
        "vault:wrong-topic-exact",
        topic_id=other_topic.id,
        created_at=since,
    )
    session.add_all([exact, topic_wide, too_old, wrong_topic])
    session.flush()

    where = ChunkFilter(concept_id=concept.id, since=since)
    scripted = ScriptedRetriever(
        {"retrieval": [wrong_topic.id, too_old.id, topic_wide.id, exact.id]}
    )
    fts_ids = {
        chunk_id
        for chunk_id, _ in FtsRetriever().search(
            session,
            "retrieval",
            where=where,
            k=10,
        )
    }
    scripted_ids = {
        chunk_id
        for chunk_id, _ in scripted.search(
            session,
            "retrieval",
            where=where,
            k=10,
        )
    }

    assert fts_ids == scripted_ids == {exact.id, topic_wide.id}


def test_ensure_fts_rebuilds_index_for_chunks_written_without_fts5():
    """Chunks indexed while FTS5 was unavailable must become searchable once it is."""
    from sqlalchemy import text
    from sqlmodel import Session, SQLModel, create_engine

    from adaptive_academy.db import ensure_fts
    from adaptive_academy.models import Chunk

    engine = create_engine("sqlite://")
    SQLModel.metadata.create_all(engine)
    # No FTS objects yet: simulate the no-FTS5 upgrade path.
    with Session(engine) as session:
        session.add(Chunk(kind="vault_note", source_ref="file:///v/a.md", ordinal=0,
                          heading="", text="quasar luminosity", content_hash="h1"))
        session.commit()
    assert ensure_fts(engine) is True
    with engine.connect() as connection:
        rows = connection.execute(
            text("SELECT rowid FROM chunk_fts WHERE chunk_fts MATCH 'quasar'")
        ).all()
    assert len(rows) == 1
