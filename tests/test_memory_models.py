import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from adaptive_academy.models import Chunk, Concept, Topic, Track, VaultLink


def _concept(session) -> tuple[Topic, Concept]:
    topic = Topic(title="Retrieval")
    session.add(topic)
    session.flush()

    track = Track(topic_id=topic.id, title="Memory")
    session.add(track)
    session.flush()

    concept = Concept(track_id=track.id, name="Contextual retrieval")
    session.add(concept)
    session.flush()
    return topic, concept


def test_chunk_round_trips_json_and_enforces_constraints(session):
    topic, concept = _concept(session)
    chunk = Chunk(
        kind="learner_output",
        topic_id=topic.id,
        concept_id=concept.id,
        source_ref="assessment:1#response",
        ordinal=0,
        heading="Retrieval > Context",
        text="The learner explains contextual retrieval.",
        context="Retrieval > Context",
        content_hash="a" * 64,
        meta={"score": 0.8, "tags": ["memory", "retrieval"]},
    )
    session.add(chunk)
    session.commit()
    session.refresh(chunk)

    assert chunk.meta == {"score": 0.8, "tags": ["memory", "retrieval"]}
    assert chunk.topic_id == topic.id
    assert chunk.concept_id == concept.id

    session.add(
        Chunk(
            kind="question",
            source_ref=chunk.source_ref,
            ordinal=chunk.ordinal,
            text="Duplicate position",
            content_hash="b" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()

    session.add(
        Chunk(
            kind="question",
            topic_id=999_999,
            concept_id=999_999,
            source_ref="assessment:missing#question",
            ordinal=0,
            text="Missing parents",
            content_hash="c" * 64,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_chunk_and_vault_link_indexes_exist(session):
    link = VaultLink(
        src_ref="file:///vault/source.md",
        dst_ref="file:///vault/target.md",
        dst_title="Target",
    )
    session.add(link)
    session.commit()

    stored = session.exec(
        select(VaultLink).where(VaultLink.dst_ref == "file:///vault/target.md")
    ).one()
    assert stored.src_ref == "file:///vault/source.md"

    inspector = inspect(session.get_bind())
    chunk_indexes = {item["name"] for item in inspector.get_indexes("chunk")}
    vault_link_indexes = {item["name"] for item in inspector.get_indexes("vaultlink")}
    assert {
        "ix_chunk_kind_concept_id",
        "ix_chunk_kind_topic_id",
        "ix_chunk_source_ref",
        "ix_chunk_created_at",
    } <= chunk_indexes
    assert {"ix_vaultlink_src_ref", "ix_vaultlink_dst_ref"} <= vault_link_indexes
