"""Concept graph population and traversal with no LLM dependencies."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, func, literal, or_
from sqlmodel import Session, col, select

from adaptive_academy.engine.aliases import normalize_name
from adaptive_academy.engine.assess import level_from_score
from adaptive_academy.engine.gates import evaluate_concept
from adaptive_academy.models import (
    Assessment,
    Concept,
    ConceptAlias,
    ConceptEdge,
    TopicFoundation,
    Track,
    now_utc,
)

MAX_TRAVERSAL_DEPTH = 6
DEFAULT_TRAVERSAL_DEPTH = 3
DEFAULT_EDGE_KINDS = ("prerequisite", "related", "alias")
LEVEL_ORDER = {"low": 0, "medium": 1, "high": 2}


@dataclass(frozen=True)
class BackfillResult:
    tracks: int
    edges: int  # Desired current edge count, not rows inserted by this call.
    unresolved: int


def resolve_concept(name: str, concepts: list[Concept]) -> Concept | None:
    """Resolve a concept by exact name, then by the shared normalized name."""
    for concept in concepts:
        if concept.name == name:
            return concept

    normalized = normalize_name(name)
    for concept in concepts:
        if normalize_name(concept.name) == normalized:
            return concept
    return None


def edges_from_prerequisite_map(
    prerequisite_map: dict,
    concepts: list[Concept],
) -> tuple[list[tuple[int, int]], list[str]]:
    """Resolve ``src requires dst`` pairs without creating missing concepts."""
    pairs: list[tuple[int, int]] = []
    seen_pairs: set[tuple[int, int]] = set()
    unresolved: list[str] = []
    seen_unresolved: set[str] = set()

    def record_unresolved(name: str) -> None:
        if name not in seen_unresolved:
            seen_unresolved.add(name)
            unresolved.append(name)

    for source_name, raw_prerequisites in prerequisite_map.items():
        if not isinstance(source_name, str):
            continue
        source = resolve_concept(source_name, concepts)
        if source is None or source.id is None:
            record_unresolved(source_name)

        if isinstance(raw_prerequisites, str):
            prerequisites = [raw_prerequisites]
        elif isinstance(raw_prerequisites, (list, tuple, set)):
            prerequisites = raw_prerequisites
        else:
            prerequisites = []

        for prerequisite_name in prerequisites:
            if not isinstance(prerequisite_name, str):
                continue
            prerequisite = resolve_concept(prerequisite_name, concepts)
            if prerequisite is None or prerequisite.id is None:
                record_unresolved(prerequisite_name)
                continue
            if source is None or source.id is None:
                continue
            if source.id == prerequisite.id:
                continue
            pair = (source.id, prerequisite.id)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                pairs.append(pair)
    return pairs, unresolved


def invalidate_track_edges(
    session: Session,
    track_id: int,
    *,
    origin: str = "researcher",
    now: datetime | None = None,
) -> int:
    """Invalidate current matching edges whose source belongs to one track."""
    invalidated_at = now if now is not None else now_utc()
    rows = session.exec(
        select(ConceptEdge)
        .join(Concept, ConceptEdge.src_concept_id == Concept.id)
        .where(
            Concept.track_id == track_id,
            ConceptEdge.origin == origin,
            col(ConceptEdge.valid_until).is_(None),
        )
    ).all()
    for edge in rows:
        edge.valid_until = invalidated_at
        session.add(edge)
    session.flush()
    return len(rows)


def insert_edges(
    session: Session,
    pairs: Iterable[tuple[int, int]],
    *,
    kind: str,
    origin: str,
    origin_ref: str = "",
    weight: float = 1.0,
) -> int:
    """Insert missing current edges and leave historical edges unchanged."""
    inserted = 0
    for source_id, destination_id in dict.fromkeys(pairs):
        current = session.exec(
            select(ConceptEdge).where(
                ConceptEdge.src_concept_id == source_id,
                ConceptEdge.dst_concept_id == destination_id,
                ConceptEdge.kind == kind,
                col(ConceptEdge.valid_until).is_(None),
            )
        ).first()
        if current is not None:
            continue
        session.add(
            ConceptEdge(
                src_concept_id=source_id,
                dst_concept_id=destination_id,
                kind=kind,
                origin=origin,
                origin_ref=origin_ref,
                weight=weight,
            )
        )
        session.flush()
        inserted += 1
    return inserted


def alias_edges(session: Session, program_id: int, canonical_name: str) -> int:
    """Insert both directions for every distinct pair in one alias group."""
    aliases = session.exec(
        select(ConceptAlias)
        .where(
            ConceptAlias.program_id == program_id,
            ConceptAlias.canonical_name == canonical_name,
        )
        .order_by(ConceptAlias.id)
    ).all()
    concept_ids = list(dict.fromkeys(alias.concept_id for alias in aliases))
    pairs = [
        (source_id, destination_id)
        for source_id in concept_ids
        for destination_id in concept_ids
        if source_id != destination_id
    ]
    origin_ref = f"alias:{aliases[0].id}" if aliases else ""
    return insert_edges(
        session,
        pairs,
        kind="alias",
        origin="alias",
        origin_ref=origin_ref,
    )


def invalidate_concept_edges(
    session: Session,
    concept_ids: Iterable[int],
    *,
    now: datetime | None = None,
) -> int:
    """Invalidate every current edge that touches any selected concept."""
    selected_ids = tuple(dict.fromkeys(concept_ids))
    if not selected_ids:
        return 0
    invalidated_at = now if now is not None else now_utc()
    rows = session.exec(
        select(ConceptEdge).where(
            col(ConceptEdge.valid_until).is_(None),
            or_(
                ConceptEdge.src_concept_id.in_(selected_ids),
                ConceptEdge.dst_concept_id.in_(selected_ids),
            ),
        )
    ).all()
    for edge in rows:
        edge.valid_until = invalidated_at
        session.add(edge)
    session.flush()
    return len(rows)


def _validity_predicate(edge_table, at: datetime | None):
    if at is None:
        return edge_table.c.valid_until.is_(None)
    return and_(
        edge_table.c.valid_from <= at,
        or_(
            edge_table.c.valid_until.is_(None),
            edge_table.c.valid_until > at,
        ),
    )


def _clamp_depth(max_depth: int) -> int:
    return max(0, min(max_depth, MAX_TRAVERSAL_DEPTH))


def _traverse(
    session: Session,
    concept_id: int,
    *,
    kind: str,
    max_depth: int,
    at: datetime | None,
    reverse: bool,
) -> list[tuple[int, int]]:
    depth_limit = _clamp_depth(max_depth)
    if depth_limit == 0:
        return []

    edge = ConceptEdge.__table__
    if reverse:
        source_column = edge.c.dst_concept_id
        destination_column = edge.c.src_concept_id
    else:
        source_column = edge.c.src_concept_id
        destination_column = edge.c.dst_concept_id

    seed = select(
        destination_column.label("concept_id"),
        literal(1).label("depth"),
    ).where(
        source_column == concept_id,
        edge.c.kind == kind,
        _validity_predicate(edge, at),
    )
    walk = seed.cte("concept_walk", recursive=True)
    recursive_step = (
        select(
            destination_column.label("concept_id"),
            (walk.c.depth + 1).label("depth"),
        )
        .select_from(edge.join(walk, source_column == walk.c.concept_id))
        .where(
            walk.c.depth < depth_limit,
            edge.c.kind == kind,
            _validity_predicate(edge, at),
        )
    )
    walk = walk.union(recursive_step)
    shortest_depth = func.min(walk.c.depth).label("depth")
    statement = (
        select(walk.c.concept_id, shortest_depth)
        .where(walk.c.concept_id != concept_id)
        .group_by(walk.c.concept_id)
        .order_by(shortest_depth, walk.c.concept_id)
    )
    return [
        (int(row.concept_id), int(row.depth))
        for row in session.exec(statement).all()
    ]


def ancestors(
    session: Session,
    concept_id: int,
    *,
    kind: str = "prerequisite",
    max_depth: int = DEFAULT_TRAVERSAL_DEPTH,
    at: datetime | None = None,
) -> list[tuple[int, int]]:
    """Return prerequisite ancestors with their shortest directed depth."""
    return _traverse(
        session,
        concept_id,
        kind=kind,
        max_depth=max_depth,
        at=at,
        reverse=False,
    )


def descendants(
    session: Session,
    concept_id: int,
    *,
    kind: str = "prerequisite",
    max_depth: int = DEFAULT_TRAVERSAL_DEPTH,
    at: datetime | None = None,
) -> list[tuple[int, int]]:
    """Return concepts that depend on this concept and their shortest depth."""
    return _traverse(
        session,
        concept_id,
        kind=kind,
        max_depth=max_depth,
        at=at,
        reverse=True,
    )


def neighbors(
    session: Session,
    concept_id: int,
    *,
    kinds: tuple[str, ...] = DEFAULT_EDGE_KINDS,
    at: datetime | None = None,
) -> list[int]:
    """Return distinct concepts connected in either direction by selected kinds."""
    if not kinds:
        return []
    edge = ConceptEdge.__table__
    outgoing = select(edge.c.dst_concept_id.label("concept_id")).where(
        edge.c.src_concept_id == concept_id,
        edge.c.dst_concept_id != concept_id,
        edge.c.kind.in_(kinds),
        _validity_predicate(edge, at),
    )
    incoming = select(edge.c.src_concept_id.label("concept_id")).where(
        edge.c.dst_concept_id == concept_id,
        edge.c.src_concept_id != concept_id,
        edge.c.kind.in_(kinds),
        _validity_predicate(edge, at),
    )
    connected = outgoing.union(incoming).subquery()
    statement = select(connected.c.concept_id).order_by(connected.c.concept_id)
    return [int(value) for value in session.exec(statement).all()]


def weakest_ancestor(
    session: Session,
    concept_id: int,
) -> tuple[int, float] | None:
    """Return the weakest assessed ancestor; exclude ancestors without assessments."""
    ancestor_ids = [
        ancestor_id
        for ancestor_id, _depth in ancestors(
            session,
            concept_id,
            max_depth=MAX_TRAVERSAL_DEPTH,
        )
    ]
    if not ancestor_ids:
        return None

    assessments = session.exec(
        select(Assessment)
        .where(Assessment.concept_id.in_(ancestor_ids))
        .order_by(Assessment.id)
    ).all()
    latest_score: dict[int, float] = {}
    for assessment in assessments:
        latest_score[assessment.concept_id] = assessment.score
    assessed_ids = [
        ancestor_id for ancestor_id in ancestor_ids if ancestor_id in latest_score
    ]
    if not assessed_ids:
        return None

    def weakness_key(ancestor_id: int) -> tuple[int, float, int]:
        score = float(latest_score[ancestor_id])
        level = level_from_score(score)[0]
        return LEVEL_ORDER[level], score, ancestor_id

    weakest_id = min(assessed_ids, key=weakness_key)
    return weakest_id, float(latest_score[weakest_id])


def frontier(session: Session, track_id: int) -> list[tuple[int, list[str]]]:
    """Return verified concepts with at least one neighbor outside their track."""
    # Concept.track_id is non-null, so "outside any track" means a different track_id.
    concepts = session.exec(
        select(Concept)
        .where(Concept.track_id == track_id)
        .order_by(Concept.id)
    ).all()
    result: list[tuple[int, list[str]]] = []
    for concept in concepts:
        if concept.id is None:
            continue
        assessments = session.exec(
            select(Assessment).where(Assessment.concept_id == concept.id)
        ).all()
        if evaluate_concept(concept.id, concept.name, assessments).verdict != "verified":
            continue

        outside = []
        for neighbor_id in neighbors(session, concept.id):
            neighbor = session.get(Concept, neighbor_id)
            if neighbor is not None and neighbor.track_id != track_id:
                outside.append(neighbor)
        outside.sort(key=lambda item: (item.name.casefold(), item.id or 0))
        outside_names = list(dict.fromkeys(item.name for item in outside))
        if outside_names:
            result.append((concept.id, outside_names))
    return result


def _current_researcher_edges(session: Session, track_id: int) -> list[ConceptEdge]:
    return session.exec(
        select(ConceptEdge)
        .join(Concept, ConceptEdge.src_concept_id == Concept.id)
        .where(
            Concept.track_id == track_id,
            ConceptEdge.origin == "researcher",
            col(ConceptEdge.valid_until).is_(None),
        )
    ).all()


def backfill(session: Session) -> BackfillResult:
    """Materialize missing researcher and alias edges without duplicating rows."""
    track_count = 0
    edge_count = 0
    unresolved_count = 0
    foundations = session.exec(
        select(TopicFoundation).order_by(TopicFoundation.id)
    ).all()
    for foundation in foundations:
        tracks = session.exec(
            select(Track)
            .where(Track.topic_id == foundation.topic_id)
            .order_by(Track.id)
        ).all()
        for track in tracks:
            if track.id is None:
                continue
            track_count += 1
            concepts = session.exec(
                select(Concept)
                .where(Concept.track_id == track.id)
                .order_by(Concept.id)
            ).all()
            pairs, unresolved = edges_from_prerequisite_map(
                foundation.prerequisite_map,
                concepts,
            )
            desired = {(source, destination, "prerequisite") for source, destination in pairs}
            current_rows = _current_researcher_edges(session, track.id)
            current = {
                (edge.src_concept_id, edge.dst_concept_id, edge.kind)
                for edge in current_rows
            }
            if current != desired or len(current_rows) != len(desired):
                invalidate_track_edges(session, track.id)
                insert_edges(
                    session,
                    pairs,
                    kind="prerequisite",
                    origin="researcher",
                    origin_ref=f"foundation:{foundation.topic_id}",
                )
            edge_count += len(desired)
            unresolved_count += len(unresolved)

    aliases = session.exec(
        select(ConceptAlias).order_by(
            ConceptAlias.program_id,
            ConceptAlias.canonical_name,
            ConceptAlias.id,
        )
    ).all()
    groups: dict[tuple[int, str], list[int]] = {}
    for alias in aliases:
        groups.setdefault(
            (alias.program_id, alias.canonical_name),
            [],
        ).append(alias.concept_id)
    for (program_id, canonical_name), concept_ids in groups.items():
        unique_ids = set(concept_ids)
        edge_count += len(unique_ids) * max(len(unique_ids) - 1, 0)
        alias_edges(session, program_id, canonical_name)

    session.flush()
    return BackfillResult(
        tracks=track_count,
        edges=edge_count,
        unresolved=unresolved_count,
    )
