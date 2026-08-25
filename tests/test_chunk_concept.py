from sqlmodel import select

from adaptive_academy.engine.memory import index_text
from adaptive_academy.models import (
    Chunk,
    ChunkConcept,
    Concept,
    ConceptAlias,
    Program,
    Topic,
    Track,
)


def _concepts(session) -> tuple[Topic, Concept, Concept, Concept]:
    topic = Topic(title="Concept tagging")
    program = Program(title="Graph program")
    session.add_all([topic, program])
    session.flush()
    track = Track(topic_id=topic.id, title="Concept tagging")
    session.add(track)
    session.flush()
    attention = Concept(track_id=track.id, name="Attention")
    aliased = Concept(track_id=track.id, name="Scaled Dot Product")
    short = Concept(track_id=track.id, name="MLP")
    session.add_all([attention, aliased, short])
    session.flush()
    session.add(
        ConceptAlias(
            program_id=program.id,
            concept_id=aliased.id,
            canonical_name="Query Key",
        )
    )
    session.flush()
    return topic, attention, aliased, short


def test_index_text_tags_concept_names_and_aliases_with_whole_word_hits(session):
    topic, attention, aliased, short = _concepts(session)

    index_text(
        session,
        kind="source_doc",
        text=(
            "Attention and ATTENTION differ from attentional. "
            "Query Key appears once. MLP stays short."
        ),
        source_ref="sourcedoc:tagged",
        topic_id=topic.id,
    )
    session.flush()

    rows = session.exec(select(ChunkConcept).order_by(ChunkConcept.concept_id)).all()
    assert {row.concept_id: row.hits for row in rows} == {
        attention.id: 2,
        aliased.id: 1,
    }
    assert short.id not in {row.concept_id for row in rows}


def test_reindex_changed_text_updates_chunk_concept_rows(session):
    topic, attention, aliased, _short = _concepts(session)
    index_text(
        session,
        kind="source_doc",
        text="Attention appears beside Query Key.",
        source_ref="sourcedoc:changed",
        topic_id=topic.id,
    )
    session.flush()
    chunk = session.exec(
        select(Chunk).where(Chunk.source_ref == "sourcedoc:changed")
    ).one()

    result = index_text(
        session,
        kind="source_doc",
        text="Query Key and query key remain; attentional does not match.",
        source_ref="sourcedoc:changed",
        topic_id=topic.id,
    )
    session.flush()

    updated = session.exec(
        select(Chunk).where(Chunk.source_ref == "sourcedoc:changed")
    ).one()
    rows = session.exec(select(ChunkConcept).where(ChunkConcept.chunk_id == chunk.id)).all()
    assert result.indexed == 1
    assert updated.id == chunk.id
    assert [(row.concept_id, row.hits) for row in rows] == [(aliased.id, 2)]
    assert attention.id not in {row.concept_id for row in rows}
