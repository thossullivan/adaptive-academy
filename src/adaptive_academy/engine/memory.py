"""Pure text chunking and indexing helpers for local memory retrieval."""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlmodel import Session, select

from adaptive_academy.engine.vault import parse_frontmatter
from adaptive_academy.llm.retriever_types import Hit
from adaptive_academy.models import (
    AgentEvent,
    Chunk,
    Concept,
    ConceptAlias,
    Track,
    VaultLink,
)

if TYPE_CHECKING:
    from adaptive_academy.llm.retriever_types import Retriever

DEFAULT_K = 6
INJECT_BUDGET_CHARS = 2400
CHUNK_TARGET_CHARS = 1200
MAX_INDEX_CHARS = 2_000_000
TUTOR_TURN_MIN_CHARS = 200
NEARDUP_JACCARD = 0.6

_HEADING_RE = re.compile(r"^(#{1,3})[ \t]+(.+?)(?:[ \t]+#+[ \t]*)?$")
_FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
_WIKILINK_RE = re.compile(r"\[\[([^\[\]\n]+)\]\]")


@dataclass(frozen=True)
class Piece:
    heading: str
    text: str
    ordinal: int


@dataclass(frozen=True)
class WikiLink:
    target: str
    alias: str
    heading: str


@dataclass(frozen=True)
class IndexResult:
    indexed: int
    skipped: int
    removed: int


@dataclass(frozen=True)
class ChunkFilter:
    """Relational constraints applied before a retriever ranks chunks."""

    kinds: tuple[str, ...] = ()
    topic_id: int | None = None
    concept_id: int | None = None
    exclude_source_refs: tuple[str, ...] = ()
    since: datetime | None = None
    source_refs: tuple[str, ...] = ()


def resolve_chunk_filter(session: Session, where: ChunkFilter) -> ChunkFilter:
    """Derive a concept's topic when the caller omits the topic filter."""
    if where.concept_id is None or where.topic_id is not None:
        return where

    concept = session.get(Concept, where.concept_id)
    if concept is None:
        return where
    track = session.get(Track, concept.track_id)
    if track is None:
        return where
    return replace(where, topic_id=track.topic_id)


def normalize(text: str) -> str:
    """Return NFC text with leading, trailing, and repeated whitespace removed."""
    normalized = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", normalized).strip()


def content_hash(text: str) -> str:
    """Return a stable hash for text after normalization."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


def sanitize_fts_query(query: str) -> str:
    """Convert arbitrary input into a safe FTS5 disjunction of quoted tokens."""
    tokens = re.findall(r"[^\W_]+", query, flags=re.UNICODE)
    kept = [token for token in tokens if len(token) >= 2]
    if not kept:
        return '""'
    return " OR ".join(f'"{token}"' for token in kept)


def expand_query(session: Session, query: str, *, concept_id: int | None) -> str:
    """Append the selected concept name and canonical alias without using an LLM."""
    if concept_id is None:
        return query

    concept = session.get(Concept, concept_id)
    alias = session.exec(
        select(ConceptAlias).where(ConceptAlias.concept_id == concept_id)
    ).first()
    additions = [concept.name if concept is not None else ""]
    additions.append(alias.canonical_name if alias is not None else "")

    expanded = query.strip()
    included = expanded.casefold()
    for addition in additions:
        addition = addition.strip()
        if addition and addition.casefold() not in included:
            expanded = f"{expanded} {addition}".strip()
            included = expanded.casefold()
    return expanded


def _split_long_paragraph(paragraph: str, target: int) -> list[str]:
    """Split one paragraph at whitespace while preserving every whole word."""
    remaining = paragraph.strip()
    chunks: list[str] = []

    while len(remaining) > target:
        boundary = None
        for match in re.finditer(r"\s+", remaining[: target + 1]):
            if match.start() > 0:
                boundary = match

        if boundary is None:
            boundary = re.search(r"\s+", remaining[target:])
            if boundary is None:
                break
            start = target + boundary.start()
            end = target + boundary.end()
        else:
            start = boundary.start()
            end = boundary.end()

        chunk = remaining[:start].rstrip()
        if chunk:
            chunks.append(chunk)
        remaining = remaining[end:].lstrip()

    if remaining:
        chunks.append(remaining)
    return chunks


def split_plain(text: str, *, target: int = CHUNK_TARGET_CHARS) -> list[Piece]:
    """Split plain text near the target size without cutting words."""
    if target <= 0:
        raise ValueError("target must be positive")

    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    pending = ""

    for paragraph in paragraphs:
        if len(paragraph) > target:
            if pending:
                chunks.append(pending)
                pending = ""
            chunks.extend(_split_long_paragraph(paragraph, target))
            continue

        candidate = f"{pending}\n\n{paragraph}" if pending else paragraph
        if len(candidate) <= target:
            pending = candidate
        else:
            chunks.append(pending)
            pending = paragraph

    if pending:
        chunks.append(pending)

    return [Piece(heading="", text=chunk, ordinal=index) for index, chunk in enumerate(chunks)]


def split_markdown(md: str, *, target: int = CHUNK_TARGET_CHARS) -> list[Piece]:
    """Split Markdown by level-one through level-three headings and paragraphs."""
    if target <= 0:
        raise ValueError("target must be positive")

    _, body = parse_frontmatter(md)
    heading_path: list[str] = []
    section_heading = ""
    section_lines: list[str] = []
    sections: list[tuple[str, str]] = []
    fence_char = ""
    fence_length = 0

    def flush_section() -> None:
        section = "\n".join(section_lines).strip()
        if section:
            sections.append((section_heading, section))

    for line in body.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not fence_char:
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = ""
                fence_length = 0
            section_lines.append(line)
            continue

        heading_match = None if fence_char else _HEADING_RE.match(line)
        if heading_match:
            flush_section()
            section_lines = []
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            heading_path = [*heading_path[: level - 1], title]
            section_heading = " > ".join(heading_path)
            continue

        section_lines.append(line)

    flush_section()

    pieces: list[Piece] = []
    for path, section in sections:
        for piece in split_plain(section, target=target):
            pieces.append(Piece(heading=path, text=piece.text, ordinal=len(pieces)))
    return pieces


def make_context(doc_title: str, heading_path: str) -> str:
    """Join a document title and heading path for contextual indexing."""
    return " > ".join(part.strip() for part in (doc_title, heading_path) if part.strip())


def extract_wikilinks(md: str) -> list[WikiLink]:
    """Extract Obsidian wikilinks outside fenced code blocks."""
    visible_lines: list[str] = []
    fence_char = ""
    fence_length = 0

    for line in md.splitlines():
        fence_match = _FENCE_RE.match(line)
        if fence_match:
            marker = fence_match.group(1)
            if not fence_char:
                fence_char = marker[0]
                fence_length = len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_length:
                fence_char = ""
                fence_length = 0
            continue
        if not fence_char:
            visible_lines.append(line)

    links: list[WikiLink] = []
    for match in _WIKILINK_RE.finditer("\n".join(visible_lines)):
        raw_target, separator, raw_alias = match.group(1).partition("|")
        raw_title, heading_separator, raw_heading = raw_target.partition("#")
        target = raw_title.strip()
        if not target:
            continue
        links.append(
            WikiLink(
                target=target,
                alias=raw_alias.strip() if separator else "",
                heading=raw_heading.strip() if heading_separator else "",
            )
        )
    return links


def index_text(
    session: Session,
    *,
    kind: str,
    text: str,
    source_ref: str,
    doc_title: str = "",
    topic_id: int | None = None,
    concept_id: int | None = None,
    heading: str = "",
    meta: dict[str, Any] | None = None,
    source_mtime: float | None = None,
    splitter: Callable[[str], list[Piece]] | None = None,
) -> IndexResult:
    """Insert or update chunks for one source without committing the session."""
    pieces = (splitter or split_plain)(text)
    existing_chunks = session.exec(
        select(Chunk).where(Chunk.source_ref == source_ref).order_by(Chunk.ordinal)
    ).all()
    existing_by_ordinal = {chunk.ordinal: chunk for chunk in existing_chunks}
    metadata = meta or {}
    indexed = 0
    skipped = 0

    for piece in pieces:
        piece_heading = piece.heading or heading
        piece_hash = content_hash(piece.text)
        existing = existing_by_ordinal.get(piece.ordinal)
        if existing is not None and existing.content_hash == piece_hash:
            skipped += 1
            continue

        context = make_context(doc_title, piece_heading)
        if existing is None:
            session.add(
                Chunk(
                    kind=kind,
                    topic_id=topic_id,
                    concept_id=concept_id,
                    source_ref=source_ref,
                    ordinal=piece.ordinal,
                    heading=piece_heading,
                    text=piece.text,
                    context=context,
                    content_hash=piece_hash,
                    meta=dict(metadata),
                    source_mtime=source_mtime,
                )
            )
        else:
            existing.kind = kind
            existing.topic_id = topic_id
            existing.concept_id = concept_id
            existing.heading = piece_heading
            existing.text = piece.text
            existing.context = context
            existing.content_hash = piece_hash
            existing.meta = dict(metadata)
            existing.source_mtime = source_mtime
            session.add(existing)
        indexed += 1

    orphans = [chunk for chunk in existing_chunks if chunk.ordinal >= len(pieces)]
    for chunk in orphans:
        session.delete(chunk)

    return IndexResult(indexed=indexed, skipped=skipped, removed=len(orphans))


def remove_source(session: Session, source_ref: str) -> int:
    """Delete every chunk for one source without committing the session."""
    chunks = session.exec(select(Chunk).where(Chunk.source_ref == source_ref)).all()
    for chunk in chunks:
        session.delete(chunk)
    return len(chunks)


def jaccard(a: str, b: str) -> float:
    """Return Jaccard similarity over case-folded normalized token sets."""
    a_tokens = set(normalize(a).casefold().split())
    b_tokens = set(normalize(b).casefold().split())
    union = a_tokens | b_tokens
    if not union:
        return 0.0
    return len(a_tokens & b_tokens) / len(union)


def retrieve(
    session: Session,
    retriever: Retriever,
    query: str,
    *,
    kinds: tuple[str, ...] = (),
    topic_id: int | None = None,
    concept_id: int | None = None,
    k: int = DEFAULT_K,
    exclude_source_refs: tuple[str, ...] = (),
    order: str = "relevance",
    since: datetime | None = None,
    expand_links: bool = False,
    event_target: dict[str, int | None] | None = None,
) -> list[Hit]:
    """Retrieve ranked chunks and emit an observability event without committing."""
    started = time.perf_counter()
    try:
        if order not in {"relevance", "recency"}:
            raise ValueError(f"unsupported retrieval order: {order}")

        expanded_query = expand_query(session, query, concept_id=concept_id)
        where = resolve_chunk_filter(
            session,
            ChunkFilter(
                kinds=kinds,
                topic_id=topic_id,
                concept_id=concept_id,
                exclude_source_refs=exclude_source_refs,
                since=since,
            ),
        )
        search_k = max(k * 3, 0) if order == "recency" else max(k, 0)
        ranked = retriever.search(session, expanded_query, where=where, k=search_k)
        candidates = _load_ranked_chunks(session, ranked, where=where)
        if order == "recency":
            candidates.sort(
                key=lambda hit: (_datetime_key(hit.chunk.created_at), hit.score),
                reverse=True,
            )
        candidates = _deduplicate_hits(candidates, limit=search_k)

        if expand_links:
            direct_hits, linked_source_refs, existing_link_hits = _partition_linked_hits(
                session,
                candidates,
                limit=max(k, 0),
            )
        else:
            direct_hits = candidates[: max(k, 0)]
            linked_source_refs = []
            existing_link_hits = []

        direct_hits = _deduplicate_hits(direct_hits, limit=max(k, 0))
        link_hits = existing_link_hits
        if linked_source_refs and len(direct_hits) < max(k, 0):
            link_where = replace(where, source_refs=tuple(linked_source_refs))
            link_ranked = retriever.search(
                session,
                expanded_query,
                where=link_where,
                k=max(len(linked_source_refs) * 3, k * 3),
            )
            link_candidates = _load_ranked_chunks(session, link_ranked, where=link_where)
            best_by_source: dict[str, Hit] = {}
            for candidate in link_candidates:
                best_by_source.setdefault(candidate.chunk.source_ref, candidate)
            for candidate in existing_link_hits:
                best_by_source.setdefault(candidate.chunk.source_ref, candidate)
            link_hits = [
                Hit(chunk=hit.chunk, score=hit.score, via="link")
                for source_ref in linked_source_refs
                if (hit := best_by_source.get(source_ref)) is not None
            ]
            link_hits.sort(key=lambda hit: hit.score, reverse=True)

        hits = _deduplicate_hits([*direct_hits, *link_hits], limit=max(k, 0))
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _add_memory_event(
            session,
            kind="memory:retrieve",
            detail=(
                f"k={k} hits={len(hits)} links="
                f"{sum(hit.via == 'link' for hit in hits)} "
                f"kinds={','.join(kinds) if kinds else 'all'} order={order} ms={elapsed_ms}"
            ),
            event_target=event_target,
        )
        return hits
    except Exception as exc:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        _add_memory_event(
            session,
            kind="memory:error",
            detail=f"{type(exc).__name__}: {exc} ms={elapsed_ms}",
            event_target=event_target,
        )
        return []


def _load_ranked_chunks(
    session: Session,
    ranked: list[tuple[int, float]],
    *,
    where: ChunkFilter,
) -> list[Hit]:
    where = resolve_chunk_filter(session, where)
    hits: list[Hit] = []
    seen_ids: set[int] = set()
    for chunk_id, score in ranked:
        if chunk_id in seen_ids:
            continue
        seen_ids.add(chunk_id)
        chunk = session.get(Chunk, chunk_id)
        if chunk is not None and _matches_filter(chunk, where):
            hits.append(Hit(chunk=chunk, score=float(score)))
    return hits


def _matches_filter(chunk: Chunk, where: ChunkFilter) -> bool:
    if where.kinds and chunk.kind not in where.kinds:
        return False
    if where.topic_id is not None and chunk.topic_id != where.topic_id:
        return False
    if where.concept_id is not None and chunk.concept_id != where.concept_id:
        admits_topic_chunk = (
            where.topic_id is not None
            and chunk.topic_id == where.topic_id
            and chunk.concept_id is None
        )
        if not admits_topic_chunk:
            return False
    if chunk.source_ref in where.exclude_source_refs:
        return False
    if where.source_refs and chunk.source_ref not in where.source_refs:
        return False
    if where.since is not None:
        if _datetime_key(chunk.created_at) < _datetime_key(where.since):
            return False
    return True


def _partition_linked_hits(
    session: Session,
    candidates: list[Hit],
    *,
    limit: int,
) -> tuple[list[Hit], list[str], list[Hit]]:
    direct_hits: list[Hit] = []
    linked_source_refs: list[str] = []
    existing_link_hits: list[Hit] = []
    seen_link_refs: set[str] = set()

    for candidate in candidates:
        if len(direct_hits) >= limit:
            break
        if candidate.chunk.source_ref in seen_link_refs:
            existing_link_hits.append(
                Hit(chunk=candidate.chunk, score=candidate.score, via="link")
            )
            continue
        direct_hits.append(candidate)
        if candidate.chunk.kind != "vault_note":
            continue
        links = session.exec(
            select(VaultLink)
            .where(
                VaultLink.src_ref == candidate.chunk.source_ref,
                VaultLink.dst_ref != "",
            )
            .order_by(VaultLink.id)
        ).all()
        for link in links:
            if link.dst_ref not in seen_link_refs:
                seen_link_refs.add(link.dst_ref)
                linked_source_refs.append(link.dst_ref)
    return direct_hits, linked_source_refs, existing_link_hits


def _deduplicate_hits(hits: list[Hit], *, limit: int) -> list[Hit]:
    unique: list[Hit] = []
    hashes: set[str] = set()
    for hit in hits:
        if len(unique) >= limit:
            break
        if hit.chunk.content_hash in hashes:
            continue
        hashes.add(hit.chunk.content_hash)
        unique.append(hit)
    return unique


def _datetime_key(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _add_memory_event(
    session: Session,
    *,
    kind: str,
    detail: str,
    event_target: dict[str, int | None] | None,
) -> None:
    allowed = {
        "conversation_id",
        "topic_id",
        "program_id",
        "roleplay_session_id",
        "paper_probe_id",
    }
    target = {
        key: value
        for key, value in (event_target or {}).items()
        if key in allowed
    }
    session.add(AgentEvent(kind=kind, detail=detail, **target))
