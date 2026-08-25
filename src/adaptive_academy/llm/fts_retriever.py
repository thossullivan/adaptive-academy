"""SQLite FTS5 retrieval backend."""

from __future__ import annotations

from typing import Any

from sqlalchemy import DateTime, bindparam, text
from sqlmodel import Session

from adaptive_academy.engine.memory import (
    ChunkFilter,
    resolve_chunk_filter,
    sanitize_fts_query,
)


class FtsRetriever:
    """Rank chunks with FTS5 BM25 after applying relational filters."""

    name = "fts"

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
        clauses: list[str] = []
        parameters: dict[str, Any] = {
            "query": sanitize_fts_query(query),
            "limit": k,
        }

        if where.kinds:
            placeholders = []
            for index, kind in enumerate(where.kinds):
                key = f"kind_{index}"
                placeholders.append(f":{key}")
                parameters[key] = kind
            clauses.append(f"c.kind IN ({', '.join(placeholders)})")

        if where.topic_id is not None:
            clauses.append("c.topic_id = :topic_id")
            parameters["topic_id"] = where.topic_id

        if where.concept_id is not None:
            parameters["concept_id"] = where.concept_id
            if where.topic_id is None:
                clauses.append("c.concept_id = :concept_id")
            else:
                clauses.append("(c.concept_id = :concept_id OR c.concept_id IS NULL)")

        if where.exclude_source_refs:
            placeholders = []
            for index, source_ref in enumerate(where.exclude_source_refs):
                key = f"exclude_{index}"
                placeholders.append(f":{key}")
                parameters[key] = source_ref
            clauses.append(f"c.source_ref NOT IN ({', '.join(placeholders)})")

        if where.source_refs:
            placeholders = []
            for index, source_ref in enumerate(where.source_refs):
                key = f"source_{index}"
                placeholders.append(f":{key}")
                parameters[key] = source_ref
            clauses.append(f"c.source_ref IN ({', '.join(placeholders)})")

        if where.since is not None:
            clauses.append("c.created_at >= :since")
            parameters["since"] = where.since

        filter_sql = ""
        if clauses:
            filter_sql = f" AND {' AND '.join(clauses)}"

        statement = text(
            "SELECT chunk_fts.rowid, bm25(chunk_fts) AS rank "
            "FROM chunk_fts "
            "JOIN chunk AS c ON c.id = chunk_fts.rowid "
            "WHERE chunk_fts MATCH :query"
            f"{filter_sql} "
            "ORDER BY rank ASC, chunk_fts.rowid ASC "
            "LIMIT :limit"
        )
        if where.since is not None:
            statement = statement.bindparams(bindparam("since", type_=DateTime()))
        rows = session.execute(statement, parameters).all()
        if not rows:
            return []

        raw_scores = [float(row.rank) for row in rows]
        best = min(raw_scores)
        worst = max(raw_scores)
        spread = worst - best
        if spread == 0:
            return [(int(row.rowid), 1.0) for row in rows]
        return [
            (int(row.rowid), (worst - float(row.rank)) / spread)
            for row in rows
        ]

    def on_index(self, session: Session, chunk_ids: list[int]) -> None:
        """Do nothing because SQLite triggers maintain the FTS5 index."""
