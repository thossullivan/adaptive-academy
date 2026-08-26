from datetime import datetime, timedelta

from adaptive_academy.engine.graph import (
    ancestors,
    descendants,
    frontier,
    neighbors,
    weakest_ancestor,
)
from adaptive_academy.models import (
    Assessment,
    Concept,
    ConceptEdge,
    KnowledgeEstimate,
    Topic,
    Track,
)

T0 = datetime(2026, 8, 1, 12, 0)


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


def _edge(
    session,
    source: Concept,
    destination: Concept,
    *,
    kind: str = "prerequisite",
    valid_until: datetime | None = None,
) -> None:
    session.add(
        ConceptEdge(
            src_concept_id=source.id,
            dst_concept_id=destination.id,
            kind=kind,
            origin="researcher",
            valid_from=T0,
            valid_until=valid_until,
        )
    )


def _six_node_graph(session) -> list[Concept]:
    _, concepts = _track(session, ["A", "B", "C", "D", "E", "F"])
    a, b, c, d, e, f = concepts
    _edge(session, a, b)
    _edge(session, b, c)
    _edge(session, b, d)
    _edge(session, c, a)
    _edge(session, d, e)
    _edge(session, e, f)
    _edge(session, a, f, valid_until=T0 + timedelta(days=2))
    _edge(session, a, e, kind="related")
    _edge(session, f, a, kind="alias")
    session.flush()
    return concepts


def test_ancestors_depth_cycle_safety_and_descendant_direction(session):
    a, b, c, d, e, f = _six_node_graph(session)

    assert ancestors(session, a.id, max_depth=1) == [(b.id, 1)]
    assert ancestors(session, a.id, max_depth=2) == [
        (b.id, 1),
        (c.id, 2),
        (d.id, 2),
    ]
    assert ancestors(session, a.id, max_depth=3) == [
        (b.id, 1),
        (c.id, 2),
        (d.id, 2),
        (e.id, 3),
    ]
    assert ancestors(session, a.id, max_depth=10) == [
        (b.id, 1),
        (c.id, 2),
        (d.id, 2),
        (e.id, 3),
        (f.id, 4),
    ]
    assert descendants(session, c.id, max_depth=2) == [(b.id, 1), (a.id, 2)]


def test_ancestors_clamps_depth_to_six(session):
    _, concepts = _track(session, list("ABCDEFGH"), title="Long chain")
    for source, destination in zip(concepts[:-1], concepts[1:], strict=True):
        _edge(session, source, destination)
    session.flush()

    result = ancestors(session, concepts[0].id, max_depth=10)

    assert max(depth for _, depth in result) == 6
    assert (concepts[6].id, 6) in result
    assert concepts[7].id not in {concept_id for concept_id, _ in result}


def test_traversal_uses_bitemporal_validity_window(session):
    a, b, _, _, _, f = _six_node_graph(session)

    assert ancestors(session, a.id, max_depth=1) == [(b.id, 1)]
    assert ancestors(
        session,
        a.id,
        max_depth=1,
        at=T0 + timedelta(days=1),
    ) == [(b.id, 1), (f.id, 1)]


def test_neighbors_honors_edge_kinds(session):
    a, b, c, _, e, f = _six_node_graph(session)

    assert neighbors(session, a.id, kinds=("prerequisite",)) == [b.id, c.id]
    assert neighbors(session, a.id, kinds=("related",)) == [e.id]
    assert neighbors(session, a.id, kinds=("alias",)) == [f.id]


def test_weakest_ancestor_orders_assessment_level_before_latest_score(session):
    a, b, c, _d, _e, _f = _six_node_graph(session)
    session.add(
        Assessment(
            concept_id=b.id,
            kind="self_explanation",
            prompt="earlier",
            score=0.9,
        )
    )
    session.add(
        Assessment(
            concept_id=b.id,
            kind="self_explanation",
            prompt="latest",
            score=0.2,
        )
    )
    session.add(
        Assessment(
            concept_id=c.id,
            kind="self_explanation",
            prompt="latest",
            score=0.6,
        )
    )
    session.flush()

    assert weakest_ancestor(session, a.id) == (b.id, 0.2)


def test_weakest_ancestor_excludes_unassessed_default_high_estimate(session):
    _, (target, unassessed) = _track(
        session,
        ["Target", "Unassessed prerequisite"],
    )
    _edge(session, target, unassessed)
    session.add(KnowledgeEstimate(concept_id=unassessed.id, level="high"))
    session.add(
        Assessment(
            concept_id=target.id,
            kind="self_explanation",
            prompt="latest",
            score=0.6,
        )
    )
    session.flush()

    assert weakest_ancestor(session, target.id) is None


def test_frontier_returns_only_verified_concepts_with_outside_neighbors(session):
    track, (solid, unsolid) = _track(session, ["Solid", "Unsolid"], title="Inside")
    _, (outside,) = _track(session, ["Outside"], title="Outside")
    _edge(session, solid, outside, kind="related")
    _edge(session, unsolid, outside, kind="related")
    session.add(
        Assessment(
            concept_id=solid.id,
            kind="teach",
            prompt="artifact",
            score=0.8,
            created_at=T0,
        )
    )
    session.add(
        Assessment(
            concept_id=solid.id,
            kind="recall",
            prompt="delayed recall",
            score=0.75,
            created_at=T0 + timedelta(days=8),
        )
    )
    session.add(
        Assessment(
            concept_id=unsolid.id,
            kind="teach",
            prompt="artifact only",
            score=0.9,
            created_at=T0,
        )
    )
    session.flush()

    assert frontier(session, track.id) == [(solid.id, ["Outside"])]
