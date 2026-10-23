"""Hybrid BM25 and sqlite-vec retrieval backend."""

from __future__ import annotations

import logging
import struct
from typing import Any

from sqlalchemy import and_, or_, text
from sqlmodel import Session, col, select

from adaptive_academy.engine.memory import (
    HYBRID_CANDIDATE_K,
    HYBRID_FILTER_BATCH,
    RRF_K,
    VECTOR_DIM,
    ChunkFilter,
    resolve_chunk_filter,
)
from adaptive_academy.llm.embedder_types import Embedder
from adaptive_academy.llm.fts_retriever import FtsRetriever
from adaptive_academy.models import Chunk

logger = logging.getLogger(__name__)
_logged_vector_failure = False


class HybridRetriever:
    """Fuse BM25 and vector ranks with reciprocal-rank fusion."""

    name = "hybrid"

    def __init__(self, fts: FtsRetriever, embedder: Embedder):
        if embedder.dim != VECTOR_DIM:
            raise ValueError(f"hybrid embeddings must have {VECTOR_DIM} dimensions")
        self.fts = fts
        self.embedder = embedder

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

        where = resolve_chunk_filter(session, where)
        lexical = self.fts.search(
            session,
            query,
            where=where,
            k=HYBRID_CANDIDATE_K,
        )
        try:
            eligible_ids = _eligible_chunk_ids(
                session, where, embedding_model=self.embedder.name
            )
            semantic = self._vector_search(session, query, eligible_ids)
        except Exception:
            _warn_vector_failure_once()
            return lexical[:k]

        fused: dict[int, float] = {}
        for ranking in (lexical, semantic):
            for rank, (chunk_id, _) in enumerate(ranking, start=1):
                fused[chunk_id] = fused.get(chunk_id, 0.0) + 1.0 / (RRF_K + rank)
        ranked = sorted(fused.items(), key=lambda item: (-item[1], item[0]))[:k]
        if not ranked:
            return []
        best_score = ranked[0][1]
        return [(chunk_id, score / best_score) for chunk_id, score in ranked]

    def _vector_search(
        self,
        session: Session,
        query: str,
        eligible_ids: list[int],
    ) -> list[tuple[int, float]]:
        if not eligible_ids:
            return []
        vectors = self.embedder.embed([query])
        _validate_vectors(vectors, expected=1, dim=self.embedder.dim)
        query_blob = _serialize_vector(vectors[0])
        distances: dict[int, float] = {}

        for start in range(0, len(eligible_ids), HYBRID_FILTER_BATCH):
            batch = eligible_ids[start : start + HYBRID_FILTER_BATCH]
            placeholders = []
            parameters: dict[str, Any] = {
                "embedding": query_blob,
                "limit": HYBRID_CANDIDATE_K,
            }
            for index, chunk_id in enumerate(batch):
                key = f"chunk_id_{index}"
                placeholders.append(f":{key}")
                parameters[key] = chunk_id
            rows = session.execute(
                text(
                    "SELECT chunk_id, distance FROM chunk_vec "
                    "WHERE embedding MATCH :embedding AND k = :limit "
                    f"AND chunk_id IN ({', '.join(placeholders)}) "
                    "ORDER BY distance"
                ),
                parameters,
            ).all()
            for row in rows:
                chunk_id = int(row.chunk_id)
                distance = float(row.distance)
                current = distances.get(chunk_id)
                if current is None or distance < current:
                    distances[chunk_id] = distance

        nearest = sorted(distances.items(), key=lambda item: (item[1], item[0]))
        return nearest[:HYBRID_CANDIDATE_K]

    def on_index(self, session: Session, chunk_ids: list[int]) -> None:
        """Embed changed chunks."""
        session.flush()
        ordered_ids = list(dict.fromkeys(chunk_ids))
        if not ordered_ids:
            return

        chunks = session.exec(select(Chunk).where(col(Chunk.id).in_(ordered_ids))).all()
        chunks_by_id = {chunk.id: chunk for chunk in chunks if chunk.id is not None}
        ordered_chunks = [chunks_by_id[chunk_id] for chunk_id in ordered_ids if chunk_id in chunks_by_id]
        if not ordered_chunks:
            return

        texts = [f"{chunk.context}\n{chunk.text}" for chunk in ordered_chunks]
        vectors = self.embedder.embed(texts)
        _validate_vectors(vectors, expected=len(ordered_chunks), dim=self.embedder.dim)
        self.store_vectors(session, list(zip(ordered_chunks, vectors, strict=True)))

    def store_vectors(
        self, session: Session, pairs: list[tuple[Chunk, list[float]]]
    ) -> None:
        """Write vectors computed earlier (engine/memory.py embed_deferred_chunks embeds
        with no transaction open, then calls this inside one short write)."""
        _validate_vectors([vector for _, vector in pairs], expected=len(pairs),
                          dim=self.embedder.dim)
        delete_statement = text("DELETE FROM chunk_vec WHERE chunk_id = :chunk_id")
        insert_statement = text(
            "INSERT INTO chunk_vec(chunk_id, embedding) VALUES (:chunk_id, :embedding)"
        )
        for chunk, vector in pairs:
            session.execute(delete_statement, {"chunk_id": chunk.id})
            session.execute(
                insert_statement,
                {"chunk_id": chunk.id, "embedding": _serialize_vector(vector)},
            )
            chunk.embedding_model = self.embedder.name
            session.add(chunk)
        session.flush()


def _eligible_chunk_ids(
    session: Session, where: ChunkFilter, *, embedding_model: str | None = None
) -> list[int]:
    """Ids allowed into the vector leg; a stale or foreign-model vector is never ranked."""
    statement = select(Chunk.id)
    if embedding_model is not None:
        statement = statement.where(Chunk.embedding_model == embedding_model)
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
        statement = statement.where(col(Chunk.source_ref).not_in(where.exclude_source_refs))
    if where.source_refs:
        statement = statement.where(col(Chunk.source_ref).in_(where.source_refs))
    if where.since is not None:
        statement = statement.where(Chunk.created_at >= where.since)
    return [chunk_id for chunk_id in session.exec(statement).all() if chunk_id is not None]


def _serialize_vector(vector: list[float]) -> bytes:
    return struct.pack(f"<{len(vector)}f", *vector)


def _validate_vectors(vectors: list[list[float]], *, expected: int, dim: int) -> None:
    if len(vectors) != expected:
        raise ValueError(f"embedder returned {len(vectors)} vectors for {expected} texts")
    if any(len(vector) != dim for vector in vectors):
        raise ValueError(f"embedder must return {dim}-dimensional vectors")


def _warn_vector_failure_once() -> None:
    global _logged_vector_failure
    if _logged_vector_failure:
        return
    _logged_vector_failure = True
    logger.warning("Vector retrieval failed; returning FTS5 results.")
