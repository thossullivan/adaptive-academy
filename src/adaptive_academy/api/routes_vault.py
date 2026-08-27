"""Obsidian vault routes — local-first interop (ingest notes as sources, export notes back).

The vault path may come from the request body or fall back to Settings.obsidian_vault_path, so
the frontend can set it (persisted client-side) without a server restart. All path validation
and file I/O live in engine/vault.py.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session

from adaptive_academy.api.deps import get_retriever, get_session
from adaptive_academy.engine.memory import REINDEX_LOCK, REINDEX_LOCK_TIMEOUT_S
from adaptive_academy.api.schemas import (
    VaultExportAllOut,
    VaultExportIn,
    VaultExportOut,
    VaultIngestIn,
    VaultIngestOut,
    VaultStatusOut,
)
from adaptive_academy.engine.vault import (
    export_all_topics,
    export_vault,
    ingest_vault,
    safe_vault_dir,
    scan_notes,
)
from adaptive_academy.llm.retriever_types import Retriever
from adaptive_academy.settings import settings

router = APIRouter(prefix="/api", tags=["vault"])


def _resolve_path(given: str) -> str:
    path = (given or settings.obsidian_vault_path or "").strip()
    if not path:
        raise HTTPException(400, "no vault path configured (set AA_OBSIDIAN_VAULT_PATH or pass one)")
    return path


@router.post("/topics/{topic_id}/vault/ingest", response_model=VaultIngestOut)
def ingest(
    topic_id: int,
    body: VaultIngestIn,
    session: Session = Depends(get_session),
    retriever: Retriever = Depends(get_retriever),
) -> VaultIngestOut:
    # Ingest reindexes the vault; serialize with /api/memory/reindex.
    if not REINDEX_LOCK.acquire(timeout=REINDEX_LOCK_TIMEOUT_S):
        raise HTTPException(409, "reindex already running")
    try:
        return _ingest_locked(topic_id, body, session, retriever)
    finally:
        REINDEX_LOCK.release()


def _ingest_locked(
    topic_id: int, body: VaultIngestIn, session: Session, retriever: Retriever
) -> VaultIngestOut:
    try:
        res = ingest_vault(
            session,
            topic_id,
            _resolve_path(body.vault_path),
            subfolder=body.subfolder,
            retriever=retriever,
        )
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return VaultIngestOut(count=res.count, titles=res.titles)


@router.post("/topics/{topic_id}/vault/export", response_model=VaultExportOut)
def export(
    topic_id: int, body: VaultExportIn, session: Session = Depends(get_session)
) -> VaultExportOut:
    try:
        res = export_vault(session, topic_id, _resolve_path(body.vault_path))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return VaultExportOut(written=res.written)


@router.post("/vault/export-all", response_model=VaultExportAllOut)
def export_all(body: VaultExportIn, session: Session = Depends(get_session)) -> VaultExportAllOut:
    try:
        res = export_all_topics(session, _resolve_path(body.vault_path))
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    return VaultExportAllOut(topics=res.topics, written=res.written)


@router.get("/vault/status", response_model=VaultStatusOut)
def status(vault_path: str = Query("")) -> VaultStatusOut:
    path = (vault_path or settings.obsidian_vault_path or "").strip()
    if not path:
        return VaultStatusOut(configured=False)
    try:
        root = safe_vault_dir(path)
    except ValueError:
        return VaultStatusOut(configured=True, path=path, exists=False, is_dir=False)
    return VaultStatusOut(
        configured=True, path=str(root), exists=True, is_dir=True, note_count=len(scan_notes(root)))
