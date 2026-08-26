"""Search and refresh the local memory index."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, select

from adaptive_academy.api.deps import get_fetcher, get_retriever, get_session
from adaptive_academy.api.routes_vault import _resolve_path
from adaptive_academy.api.schemas import (
    MemoryHitOut,
    MemoryReindexIn,
    MemoryReindexOut,
    MemorySearchOut,
    MemoryStatsOut,
)
from adaptive_academy.engine.memory import (
    DEFAULT_K,
    MEMORY_SNIPPET_CHARS,
    REINDEX_DEADLINE_S,
    REINDEX_KINDS,
    normalize,
    reindex_topic,
    retrieve,
)
from adaptive_academy.llm.retriever_types import Hit, Retriever
from adaptive_academy.models import Chunk, Concept, Topic

router = APIRouter(prefix="/api/memory", tags=["memory"])
_reindex_lock = threading.Lock()
_REINDEX_LOCK_TIMEOUT_S = 0.5


def memory_hit_out(hit: Hit) -> MemoryHitOut:
    """Convert one internal retrieval hit into the public disclosure shape."""
    snippet = normalize(hit.chunk.text)
    if len(snippet) > MEMORY_SNIPPET_CHARS:
        snippet = snippet[: MEMORY_SNIPPET_CHARS - 1].rstrip() + "…"
    return MemoryHitOut(
        chunk_id=hit.chunk.id,
        kind=hit.chunk.kind,
        heading=hit.chunk.heading,
        snippet=snippet,
        score=hit.score,
        source_ref=hit.chunk.source_ref,
    )


def _parse_kinds(values: list[str] | None) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            kind
            for value in values or []
            for part in value.split(",")
            if (kind := part.strip())
        )
    )


@router.get("/search", response_model=MemorySearchOut)
def search_memory(
    q: str = Query(""),
    topic_id: int | None = None,
    concept_id: int | None = None,
    kinds: list[str] | None = Query(None),
    k: int = Query(DEFAULT_K, ge=1, le=50),
    session: Session = Depends(get_session),
    retriever: Retriever = Depends(get_retriever),
) -> MemorySearchOut:
    query = q.strip()
    if not query:
        raise HTTPException(400, "memory search query is blank")
    if topic_id is not None and session.get(Topic, topic_id) is None:
        raise HTTPException(404, "topic not found")
    if concept_id is not None and session.get(Concept, concept_id) is None:
        raise HTTPException(404, "concept not found")
    event_target = {"topic_id": topic_id} if topic_id is not None else None
    hits = retrieve(
        session,
        retriever,
        query,
        kinds=_parse_kinds(kinds),
        topic_id=topic_id,
        concept_id=concept_id,
        k=k,
        event_target=event_target,
    )
    output = MemorySearchOut(hits=[memory_hit_out(hit) for hit in hits])
    session.commit()
    return output


@router.post("/reindex", response_model=MemoryReindexOut)
def reindex_memory(
    body: MemoryReindexIn,
    session: Session = Depends(get_session),
    fetch: Callable[[str], str | None] = Depends(get_fetcher),
    retriever: Retriever = Depends(get_retriever),
) -> MemoryReindexOut | JSONResponse:
    if not _reindex_lock.acquire(timeout=_REINDEX_LOCK_TIMEOUT_S):
        raise HTTPException(409, "reindex already running")
    try:
        return _reindex_memory_locked(body, session, fetch, retriever)
    finally:
        _reindex_lock.release()


def _reindex_memory_locked(
    body: MemoryReindexIn,
    session: Session,
    fetch: Callable[[str], str | None],
    retriever: Retriever,
) -> MemoryReindexOut | JSONResponse:
    kinds = REINDEX_KINDS if body.kinds is None else _parse_kinds(body.kinds)
    unsupported_kinds = sorted(set(kinds) - set(REINDEX_KINDS))
    if unsupported_kinds:
        raise HTTPException(
            400,
            f"unsupported reindex kinds: {', '.join(unsupported_kinds)}",
        )
    vault_path = _resolve_path(body.vault_path) if "vault_note" in kinds else ""
    topic_statement = select(Topic).order_by(Topic.id)
    if body.topic_id is not None:
        topic_statement = topic_statement.where(Topic.id == body.topic_id)
    topics = session.exec(topic_statement).all()
    if body.topic_id is not None and not topics:
        raise HTTPException(404, "topic not found")

    # All-topic sweeps re-index only the notes each topic already owns; a topic never
    # claims another topic's notes, and new notes need an explicit topic_id.
    vault_refs_by_topic: dict[int, set[str]] | None = None
    note = ""
    if body.topic_id is None and "vault_note" in kinds:
        vault_refs_by_topic = {}
        for owner_id, source_ref in session.exec(
            select(Chunk.topic_id, Chunk.source_ref)
            .where(Chunk.kind == "vault_note")
            .distinct()
        ).all():
            if owner_id is not None:
                vault_refs_by_topic.setdefault(owner_id, set()).add(source_ref)
        if not vault_refs_by_topic:
            note = "no topic owns vault notes yet; pass topic_id to index new vault notes"

    started = time.perf_counter()
    indexed = 0
    skipped = 0
    removed = 0
    truncated = False
    for topic in topics:
        topic_kinds = tuple(
            kind
            for kind in kinds
            if kind != "vault_note"
            or vault_refs_by_topic is None
            or topic.id in vault_refs_by_topic
        )
        if not topic_kinds:
            continue
        only_refs = None if vault_refs_by_topic is None else vault_refs_by_topic.get(topic.id)
        remaining = REINDEX_DEADLINE_S - (time.perf_counter() - started)
        if remaining <= 0:
            truncated = True
            break
        try:
            result = reindex_topic(
                session,
                topic.id,
                vault_path=vault_path,
                fetch=fetch,
                kinds=topic_kinds,
                deadline_s=remaining,
                vault_only_refs=only_refs,
                retriever=retriever,
            )
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except (IntegrityError, OperationalError):
            session.rollback()
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            output = MemoryReindexOut(
                indexed=indexed,
                skipped=skipped,
                removed=removed,
                truncated=True,
                ms=elapsed_ms,
                note=(
                    "database conflict; partial counts: "
                    f"indexed={indexed} skipped={skipped} removed={removed}"
                ),
            )
            return JSONResponse(
                status_code=409,
                content=output.model_dump(mode="json"),
            )
        indexed += result.indexed
        skipped += result.skipped
        removed += result.removed
        if result.truncated:
            truncated = True
            break

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return MemoryReindexOut(
        indexed=indexed,
        skipped=skipped,
        removed=removed,
        truncated=truncated,
        ms=elapsed_ms,
        note=note,
    )


@router.get("/stats", response_model=MemoryStatsOut)
def memory_stats(
    topic_id: int | None = None,
    session: Session = Depends(get_session),
    retriever: Retriever = Depends(get_retriever),
) -> MemoryStatsOut:
    statement = select(Chunk.kind, Chunk.created_at)
    if topic_id is not None:
        statement = statement.where(Chunk.topic_id == topic_id)
    rows = session.exec(statement).all()
    by_kind: dict[str, int] = {}
    last_indexed_at = None
    for kind, created_at in rows:
        by_kind[kind] = by_kind.get(kind, 0) + 1
        if last_indexed_at is None or created_at > last_indexed_at:
            last_indexed_at = created_at
    return MemoryStatsOut(
        by_kind=dict(sorted(by_kind.items())),
        last_indexed_at=last_indexed_at,
        retriever=retriever.name,
    )
