import pytest
from sqlalchemy.exc import IntegrityError

from adaptive_academy.models import (
    Chunk,
    ChunkConcept,
    Concept,
    ConceptEdge,
    Program,
    Topic,
    TopicSuggestion,
    Track,
)


def _concepts(session) -> tuple[Concept, Concept]:
    topic = Topic(title="Graph models")
    session.add(topic)
    session.flush()

    track = Track(topic_id=topic.id, title="Graph")
    session.add(track)
    session.flush()

    source = Concept(track_id=track.id, name="Transformers")
    destination = Concept(track_id=track.id, name="Attention")
    session.add(source)
    session.add(destination)
    session.flush()
    return source, destination


def test_concept_edge_roundtrip_and_foreign_keys(session):
    source, destination = _concepts(session)
    edge = ConceptEdge(
        src_concept_id=source.id,
        dst_concept_id=destination.id,
        kind="prerequisite",
        origin="researcher",
    )
    session.add(edge)
    session.commit()
    session.refresh(edge)

    assert edge.weight == 1.0
    assert edge.origin_ref == ""
    assert edge.valid_from is not None
    assert edge.valid_until is None
    assert edge.recorded_at is not None

    session.add(
        ConceptEdge(
            src_concept_id=999_999,
            dst_concept_id=destination.id,
            kind="related",
            origin="learner",
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_chunk_concept_pair_is_unique(session):
    source, _ = _concepts(session)
    chunk = Chunk(
        kind="source_doc",
        source_ref="sourcedoc:1",
        text="Transformers use attention.",
        content_hash="a" * 64,
    )
    session.add(chunk)
    session.flush()

    session.add(ChunkConcept(chunk_id=chunk.id, concept_id=source.id, hits=2))
    session.commit()

    session.add(ChunkConcept(chunk_id=chunk.id, concept_id=source.id))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_topic_suggestion_evidence_roundtrip(session):
    program = Program(title="Graph program")
    session.add(program)
    session.flush()
    evidence = [
        {"kind": "chunk", "ref": "message:12"},
        {"kind": "concept", "id": 42},
    ]
    suggestion = TopicSuggestion(
        program_id=program.id,
        title="Sparse attention",
        rationale="This extends the current frontier.",
        candidate_kind="extension",
        evidence=evidence,
        score=0.85,
    )
    session.add(suggestion)
    session.commit()
    session.refresh(suggestion)

    assert suggestion.evidence == evidence
    assert suggestion.status == "proposed"
    assert suggestion.created_at is not None
    assert suggestion.decided_at is None
