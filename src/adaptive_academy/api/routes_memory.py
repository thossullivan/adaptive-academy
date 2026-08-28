"""Search and refresh the local memory index."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, col, select

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
    topic_id_for_concept,
    REINDEX_LOCK,
    REINDEX_LOCK_TIMEOUT_S,
    REINDEX_TOPIC_BATCH,
    DEFAULT_K,
    MEMORY_SNIPPET_CHARS,
    REINDEX_DEADLINE_S,
    REINDEX_KINDS,
    normalize,
    reindex_topic,
    retrieve,
)
from adaptive_academy.llm.retriever_types import Hit, Retriever
from adaptive_academy.models import AgentEvent, Chunk, Concept, Topic

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/memory", tags=["memory"])
_reindex_lock = REINDEX_LOCK  # shared with the vault ingest route
_REINDEX_LOCK_TIMEOUT_S = REINDEX_LOCK_TIMEOUT_S


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
    if concept_id is not None:
        concept = session.get(Concept, concept_id)
        if concept is None:
            raise HTTPException(404, "concept not found")
        owner_topic_id = topic_id_for_concept(session, concept_id)
        if topic_id is not None and owner_topic_id is not None and owner_topic_id != topic_id:
            raise HTTPException(400, "concept does not belong to this topic")
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
    persist_trace_async(session)
    return output


# Tests join this to observe the trace write deterministically.
last_trace_writer: threading.Thread | None = None


def persist_trace_async(session: Session) -> threading.Thread | None:
    """Write the pending memory:* trace rows from a worker thread.

    A search is a read; its trace row must never make the request wait on SQLite's
    write lock (a long agent run can hold it for a minute) nor turn hits into a 500
    (F5). The worker uses its own session and the engine's busy timeout; if the lock
    is still held after that, the trace is dropped with a warning.
    """
    global last_trace_writer
    pending = [obj for obj in session.new if isinstance(obj, AgentEvent)]
    if not pending:
        return None
    for obj in pending:
        session.expunge(obj)
    bind = session.get_bind()

    def _write() -> None:
        try:
            with Session(bind) as worker:
                for row in pending:
                    worker.add(row)
                worker.commit()
        except OperationalError as exc:
            logger.warning("memory trace dropped (%d rows): %s", len(pending), exc)

    thread = threading.Thread(target=_write, name="memory-trace", daemon=True)
    thread.start()
    last_trace_writer = thread
    return thread


@router.post("/reindex", response_model=MemoryReindexOut)
def reindex_memory(
    body: MemoryReindexIn,
    session: Session = Depends(get_session),
    fetch: Callable[[str], str | None] = Depends(get_fetcher),
    retriever: Retriever = Depends(get_retriever),
) -> MemoryReindexOut | JSONResponse:
    if not _reindex_lock.acquire(timeout=_REINDEX_LOCK_TIMEOUT_S):
        raise HTTPException(409, "reindex already running")
    started = time.perf_counter()
    progress = {"indexed": 0, "skipped": 0, "removed": 0}
    try:
        return _reindex_memory_locked(body, session, fetch, retriever, progress, started)
    except (IntegrityError, OperationalError):
        # Every DB step (topic lookup, ownership query, per-topic work) lands here; work
        # committed before the conflict is reported from `progress`, not lost.
        session.rollback()
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        output = MemoryReindexOut(
            indexed=progress["indexed"],
            skipped=progress["skipped"],
            removed=progress["removed"],
            truncated=True,
            ms=elapsed_ms,
            note=(
                "database conflict; partial counts: "
                f"indexed={progress['indexed']} skipped={progress['skipped']} "
                f"removed={progress['removed']}"
            ),
        )
        return JSONResponse(status_code=409, content=output.model_dump(mode="json"))
    finally:
        _reindex_lock.release()


def _reindex_memory_locked(
    body: MemoryReindexIn,
    session: Session,
    fetch: Callable[[str], str | None],
    retriever: Retriever,
    progress: dict[str, int],
    started: float,
) -> MemoryReindexOut | JSONResponse:
    kinds = REINDEX_KINDS if body.kinds is None else _parse_kinds(body.kinds)
    unsupported_kinds = sorted(set(kinds) - set(REINDEX_KINDS))
    if unsupported_kinds:
        raise HTTPException(
            400,
            f"unsupported reindex kinds: {', '.join(unsupported_kinds)}",
        )
    vault_path = _resolve_path(body.vault_path) if "vault_note" in kinds else ""
    deadline = started + REINDEX_DEADLINE_S
    all_topics = body.topic_id is None
    if not all_topics and session.get(Topic, body.topic_id) is None:
        raise HTTPException(404, "topic not found")

    # All-topic sweeps re-index only the notes each topic already owns; a topic never
    # claims another topic's notes, and new notes need an explicit topic_id. Ownership is
    # discovered per topic (bounded), never as one global materialization.
    note = ""
    if all_topics and "vault_note" in kinds and time.perf_counter() < deadline:
        any_owner = session.exec(
            select(Chunk.id)
            .where(Chunk.kind == "vault_note", col(Chunk.topic_id).is_not(None))
            .limit(1)
        ).first()
        if any_owner is None:
            note = "no topic owns vault notes yet; pass topic_id to index new vault notes"

    truncated = False
    last_topic_id = 0
    while True:
        # Deadline before every query, including the first topic lookup.
        if time.perf_counter() >= deadline:
            truncated = True
            break
        topic_statement = select(Topic).where(Topic.id > last_topic_id).order_by(Topic.id)
        if not all_topics:
            topic_statement = topic_statement.where(Topic.id == body.topic_id)
        topics = session.exec(topic_statement.limit(REINDEX_TOPIC_BATCH)).all()
        if not topics:
            break
        last_topic_id = max(topic.id for topic in topics if topic.id is not None)
        for topic in topics:
            if time.perf_counter() >= deadline:
                truncated = True
                break
            only_refs: set[str] | None = None
            topic_kinds = kinds
            if all_topics and "vault_note" in kinds:
                only_refs, refs_complete = _owned_vault_refs(session, topic.id, deadline)
                if not refs_complete:
                    # Ownership enumeration did not finish inside the budget: do not sweep
                    # this topic's vault with a partial ownership set.
                    truncated = True
                    break
                if not only_refs:
                    topic_kinds = tuple(kind for kind in kinds if kind != "vault_note")
            if not topic_kinds:
                continue
            remaining = deadline - time.perf_counter()
            if remaining <= 0:
                truncated = True
                break
            result = _reindex_one_topic(
                session, topic.id, vault_path, fetch, retriever, progress,
                kinds=topic_kinds, deadline_s=remaining, only_refs=only_refs,
            )
            if result.truncated:
                truncated = True
                break
        if truncated:
            break

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    return MemoryReindexOut(
        indexed=progress["indexed"],
        skipped=progress["skipped"],
        removed=progress["removed"],
        truncated=truncated,
        ms=elapsed_ms,
        note=note,
    )


def _owned_vault_refs(session: Session, topic_id: int, deadline: float) -> tuple[set[str], bool]:
    """Distinct vault-note refs a topic owns, in deadline-checked keyset batches."""
    refs: set[str] = set()
    last_id = 0
    while True:
        if time.perf_counter() >= deadline:
            return refs, False
        rows = session.exec(
            select(Chunk.id, Chunk.source_ref)
            .where(Chunk.kind == "vault_note", Chunk.topic_id == topic_id, Chunk.id > last_id)
            .order_by(Chunk.id)
            .limit(REINDEX_TOPIC_BATCH)
        ).all()
        if not rows:
            return refs, True
        last_id = max(chunk_id for chunk_id, _ in rows)
        refs.update(ref for _, ref in rows)


def _reindex_one_topic(session, topic_id, vault_path, fetch, retriever, progress, *,
                       kinds, deadline_s, only_refs):
    try:
        return reindex_topic(
            session,
            topic_id,
            vault_path=vault_path,
            fetch=fetch,
            kinds=kinds,
            deadline_s=deadline_s,
            vault_only_refs=only_refs,
            retriever=retriever,
            progress=progress,
        )
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc



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
