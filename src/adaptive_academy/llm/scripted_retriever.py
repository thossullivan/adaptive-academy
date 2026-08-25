"""Deterministic retrieval backend for tests and FTS5 fallback."""

from __future__ import annotations

import re

from sqlalchemy import and_, or_
from sqlmodel import Session, col, select

from adaptive_academy.engine.memory import ChunkFilter
from adaptive_academy.models import Chunk

_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


class ScriptedRetriever:
    """Return scripted ids or rank chunks by query-token overlap."""

    name = "scripted"

    def __init__(self, hits: dict[str, list[int]] | None = None):
        self.hits = hits

    def search(
        self,
        session: Session,
        query: str,
        *,
        where: ChunkFilter,
        k: int,
    ) -> list[tuple[int, float]]:
        if k <= 0:
            return []

        statement = select(Chunk)
        if where.kinds:
            statement = statement.where(col(Chunk.kind).in_(where.kinds))
        if where.topic_id is not None:
            statement = statement.where(Chunk.topic_id == where.topic_id)
        if where.concept_id is not None:
            concept_clause = Chunk.concept_id == where.concept_id
            if where.topic_id is not None:
                concept_clause = or_(
                    concept_clause,
                    and_(
                        col(Chunk.concept_id).is_(None),
                        Chunk.topic_id == where.topic_id,
                    ),
                )
            statement = statement.where(concept_clause)
        if where.exclude_source_refs:
            statement = statement.where(
                col(Chunk.source_ref).not_in(where.exclude_source_refs)
            )
        if where.source_refs:
            statement = statement.where(col(Chunk.source_ref).in_(where.source_refs))
        if where.since is not None:
            statement = statement.where(Chunk.created_at >= where.since)

        chunks = session.exec(statement).all()
        chunks_by_id = {chunk.id: chunk for chunk in chunks if chunk.id is not None}

        if self.hits is not None:
            scripted_ids = self.hits.get(query, [])
            eligible_ids = [chunk_id for chunk_id in scripted_ids if chunk_id in chunks_by_id]
            total = len(eligible_ids)
            return [
                (chunk_id, 1.0 if total == 1 else 1.0 - (index / total))
                for index, chunk_id in enumerate(eligible_ids[:k])
            ]

        query_tokens = _tokens(query)
        ranked: list[tuple[int, float]] = []
        for chunk_id, chunk in chunks_by_id.items():
            chunk_tokens = _tokens(f"{chunk.context} {chunk.text}")
            overlap = len(query_tokens & chunk_tokens)
            if overlap:
                ranked.append((chunk_id, overlap / len(query_tokens)))
        ranked.sort(key=lambda item: (-item[1], item[0]))
        return ranked[:k]

    def on_index(self, session: Session, chunk_ids: list[int]) -> None:
        """Do nothing because the Python fallback has no secondary index."""


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in _TOKEN_RE.findall(text)}
