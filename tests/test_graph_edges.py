from datetime import datetime, timezone

from sqlmodel import select

from adaptive_academy.engine.graph import (
    BackfillResult,
    alias_edges,
    backfill,
    edges_from_prerequisite_map,
    insert_edges,
    invalidate_concept_edges,
    invalidate_track_edges,
    resolve_concept,
)
from adaptive_academy.models import (
    Concept,
    ConceptAlias,
    ConceptEdge,
    Program,
    Topic,
    TopicFoundation,
    Track,
)


def _track(session, names: list[str], *, title: str = "Graph") -> tuple[Track, list[Concept]]:
    topic = Topic(title=title)
    session.add(topic)
    session.flush()
    track = Track(topic_id=topic.id, title=title)
    session.add(track)
    session.flush()
    concepts = [Concept(track_id=track.id, name=name) for name in names]
    session.add_all(concepts)
    session.flush()
    return track, concepts


def test_prerequisite_map_resolves_exact_normalized_and_unknown_names(session):
    _, concepts = _track(
        session,
        ["Transformer", "Attention", "Self-Attention"],
    )
    transformer, attention, self_attention = concepts

    assert resolve_concept("Attention", concepts) is attention
    assert resolve_concept("  SELF-ATTENTION  ", concepts) is self_attention
    assert resolve_concept("Unknown", concepts) is None

    pairs, unresolved = edges_from_prerequisite_map(
        {
            "Transformer": ["attention", "  SELF-ATTENTION  ", "Unknown"],
        },
        concepts,
    )

    assert pairs == [
        (transformer.id, attention.id),
        (transformer.id, self_attention.id),
    ]
    assert unresolved == ["Unknown"]


def test_insert_edges_is_idempotent(session):
    _, (source, destination) = _track(session, ["Source", "Destination"])
    pairs = [(source.id, destination.id)]

    assert insert_edges(
        session,
        pairs,
        kind="prerequisite",
        origin="researcher",
    ) == 1
    assert insert_edges(
        session,
        pairs,
        kind="prerequisite",
        origin="researcher",
    ) == 0
    assert len(session.exec(select(ConceptEdge)).all()) == 1


def test_invalidate_track_edges_keeps_history_and_allows_reinsert(session):
    track, (source, destination) = _track(session, ["Source", "Destination"])
    pairs = [(source.id, destination.id)]
    insert_edges(
        session,
        pairs,
        kind="prerequisite",
        origin="researcher",
    )
    original = session.exec(select(ConceptEdge)).one()
    invalidated_at = datetime(2026, 8, 25, 12, 0, tzinfo=timezone.utc)

    assert invalidate_track_edges(
        session,
        track.id,
        now=invalidated_at,
    ) == 1
    assert original.valid_until == invalidated_at
    assert insert_edges(
        session,
        pairs,
        kind="prerequisite",
        origin="researcher",
    ) == 1

    rows = session.exec(select(ConceptEdge).order_by(ConceptEdge.id)).all()
    assert len(rows) == 2
    assert rows[0].id == original.id
    assert rows[0].valid_until == invalidated_at
    assert rows[1].valid_until is None


def test_alias_group_creates_both_directions_and_is_idempotent(session):
    _, concepts = _track(session, ["Attention", "attention", "ATTENTION"])
    program = Program(title="Program")
    session.add(program)
    session.flush()
    for concept in concepts:
        session.add(
            ConceptAlias(
                program_id=program.id,
                canonical_name="attention",
                concept_id=concept.id,
            )
        )
    session.flush()

    assert alias_edges(session, program.id, "attention") == 6
    assert alias_edges(session, program.id, "attention") == 0

    rows = session.exec(
        select(ConceptEdge).where(ConceptEdge.kind == "alias")
    ).all()
    assert {(row.src_concept_id, row.dst_concept_id) for row in rows} == {
        (left.id, right.id)
        for left in concepts
        for right in concepts
        if left.id != right.id
    }


def test_invalidate_concept_edges_touches_both_directions(session):
    _, (first, second, third) = _track(session, ["First", "Second", "Third"])
    insert_edges(
        session,
        [(first.id, second.id), (third.id, first.id), (second.id, third.id)],
        kind="related",
        origin="learner",
    )

    assert invalidate_concept_edges(session, [first.id]) == 2
    rows = session.exec(select(ConceptEdge).order_by(ConceptEdge.id)).all()
    assert [row.valid_until is not None for row in rows] == [True, True, False]


def test_backfill_twice_has_stable_counts_and_rows(session):
    track, (transformer, attention, softmax) = _track(
        session,
        ["Transformer", "Attention", "Softmax"],
    )
    session.add(
        TopicFoundation(
            topic_id=track.topic_id,
            key_concepts=[concept.name for concept in (transformer, attention, softmax)],
            prerequisite_map={
                "Transformer": ["Attention"],
                "Attention": ["Softmax"],
            },
        )
    )

    _, (other_attention,) = _track(session, ["attention"], title="Other")
    program = Program(title="Program")
    session.add(program)
    session.flush()
    for concept in (attention, other_attention):
        session.add(
            ConceptAlias(
                program_id=program.id,
                canonical_name="attention",
                concept_id=concept.id,
            )
        )
    session.flush()

    first = backfill(session)
    first_rows = session.exec(select(ConceptEdge)).all()
    second = backfill(session)
    second_rows = session.exec(select(ConceptEdge)).all()

    assert first == BackfillResult(tracks=1, edges=4, unresolved=0)
    assert second == first
    assert len(first_rows) == len(second_rows) == 4
    assert sum(row.valid_until is None for row in second_rows) == 4
