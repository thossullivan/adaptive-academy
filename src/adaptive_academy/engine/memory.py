"""Pure text chunking and indexing helpers for local memory retrieval."""

from __future__ import annotations

import hashlib
import math
import re
import threading
import time
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from sqlalchemy import or_
from sqlmodel import Session, col, select

from adaptive_academy.engine.fetch import fetch_artifact_text
from adaptive_academy.engine.vault import parse_frontmatter
from adaptive_academy.llm.retriever_types import Hit
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Chunk,
    ChunkConcept,
    Concept,
    ConceptAlias,
    Conversation,
    Message,
    PaperProbe,
    PaperProbeAnswer,
    ProgramTopicLink,
    RoleplayTurn,
    SourceDoc,
    Track,
    VaultLink,
)

if TYPE_CHECKING:
    from adaptive_academy.engine.levels import Levels
    from adaptive_academy.llm.embedder_types import Embedder
    from adaptive_academy.llm.retriever_types import Retriever

DEFAULT_K = 6
INJECT_BUDGET_CHARS = 2400
MEMORY_SNIPPET_CHARS = 240
REINDEX_KINDS = ("vault_note", "source_doc")
REINDEX_DEADLINE_S = 60.0
# One reindex at a time per process (vault ingest and /api/memory/reindex share it).
REINDEX_LOCK = threading.Lock()
REINDEX_LOCK_TIMEOUT_S = 0.5


def bump_progress(progress: dict[str, int] | None, **deltas: int) -> None:
    """Add per-unit counts to a caller-owned progress dict (survives a later conflict)."""
    if progress is None:
        return
    for key, value in deltas.items():
        progress[key] = progress.get(key, 0) + value
TUTOR_GROUNDING_K = 4
TUTOR_COVERED_K = 3
GROUNDING_K = 3
AVOID_K = 5
MEMORY_MARKER = "MEMORY"
ALREADY_COVERED_MARKER = "ALREADY_COVERED"
CHUNK_TARGET_CHARS = 1200
MAX_INDEX_CHARS = 2_000_000
TUTOR_TURN_MIN_CHARS = 200
NEARDUP_JACCARD = 0.6
NEARDUP_COSINE = 0.86
VECTOR_DIM = 384
HYBRID_CANDIDATE_K = 20
RRF_K = 60
HYBRID_FILTER_BATCH = 500
QUERY_NEIGHBOR_LIMIT = 3

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
    truncated: bool = False


@dataclass(frozen=True)
class ReindexResult:
    indexed: int
    skipped: int
    removed: int
    truncated: bool
    ms: int


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
    operators = {"and", "or", "not", "near"}
    kept = [
        token
        for token in tokens
        if len(token) >= 2 and token.casefold() not in operators
    ]
    if not kept:
        return '""'
    return " OR ".join(f'"{token}"' for token in kept)


def expand_query(session: Session, query: str, *, concept_id: int | None) -> str:
    """Append the concept, canonical alias, and up to three graph neighbors."""
    if concept_id is None:
        return query

    from adaptive_academy.engine import graph

    concept = session.get(Concept, concept_id)
    alias = session.exec(
        select(ConceptAlias).where(ConceptAlias.concept_id == concept_id)
    ).first()
    additions = [concept.name if concept is not None else ""]
    additions.append(alias.canonical_name if alias is not None else "")
    neighbor_names: list[str] = []
    for neighbor_id in graph.neighbors(session, concept_id):
        neighbor = session.get(Concept, neighbor_id)
        if neighbor is None:
            continue
        neighbor_names.append(neighbor.name)
        if len(neighbor_names) == QUERY_NEIGHBOR_LIMIT:
            break
    additions.extend(neighbor_names)

    expanded = query.strip()
    included = expanded.casefold()
    for addition in additions:
        addition = addition.strip()
        if addition and addition.casefold() not in included:
            expanded = f"{expanded} {addition}".strip()
            included = expanded.casefold()
    return expanded


def concept_name_index(session: Session, topic_id: int) -> list[tuple[int, str]]:
    """Return concept and canonical alias names for one topic."""
    concepts = session.exec(
        select(Concept)
        .join(Track)
        .where(Track.topic_id == topic_id)
        .order_by(Concept.id)
    ).all()
    concept_ids = [concept.id for concept in concepts if concept.id is not None]
    if not concept_ids:
        return []

    aliases = session.exec(
        select(ConceptAlias)
        .where(ConceptAlias.concept_id.in_(concept_ids))
        .order_by(ConceptAlias.id)
    ).all()
    aliases_by_concept: dict[int, list[str]] = {}
    for alias in aliases:
        aliases_by_concept.setdefault(alias.concept_id, []).append(alias.canonical_name)

    names: list[tuple[int, str]] = []
    for concept in concepts:
        if concept.id is None:
            continue
        names.append((concept.id, concept.name))
        names.extend(
            (concept.id, alias_name)
            for alias_name in aliases_by_concept.get(concept.id, [])
        )
    return names


def tag_chunk_concepts(
    session: Session,
    chunk: Chunk,
    names: list[tuple[int, str]],
) -> int:
    """Replace one chunk's concept links using whole-word name matches."""
    if chunk.id is None:
        session.flush()
    if chunk.id is None:
        raise ValueError("chunk must be flushed before concept tagging")

    searchable_text = f"{chunk.context}\n{chunk.text}"
    hits_by_concept: dict[int, int] = {}
    seen_names: set[tuple[int, str]] = set()
    for concept_id, raw_name in names:
        name = raw_name.strip()
        name_key = (concept_id, name.casefold())
        if len(name) < 4 or name_key in seen_names:
            continue
        seen_names.add(name_key)
        hits = len(
            re.findall(
                rf"(?<!\w){re.escape(name)}(?!\w)",
                searchable_text,
                flags=re.IGNORECASE,
            )
        )
        if hits:
            hits_by_concept[concept_id] = hits_by_concept.get(concept_id, 0) + hits

    existing_rows = session.exec(
        select(ChunkConcept).where(ChunkConcept.chunk_id == chunk.id)
    ).all()
    existing_by_concept = {row.concept_id: row for row in existing_rows}
    for concept_id, hits in hits_by_concept.items():
        row = existing_by_concept.pop(concept_id, None)
        if row is None:
            row = ChunkConcept(
                chunk_id=chunk.id,
                concept_id=concept_id,
                hits=hits,
            )
        else:
            row.hits = hits
        session.add(row)
    for stale_row in existing_by_concept.values():
        session.delete(stale_row)
    return len(hits_by_concept)


def _delete_chunk_concept_rows(session: Session, chunks: list[Chunk]) -> None:
    chunk_ids = [chunk.id for chunk in chunks if chunk.id is not None]
    if not chunk_ids:
        return
    rows = session.exec(
        select(ChunkConcept).where(ChunkConcept.chunk_id.in_(chunk_ids))
    ).all()
    for row in rows:
        session.delete(row)
    session.flush()


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
    retriever: Retriever | None = None,
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
    changed_chunks: list[Chunk] = []
    active_chunks: list[Chunk] = []

    for piece in pieces:
        piece_heading = piece.heading or heading
        piece_hash = content_hash(piece.text)
        existing = existing_by_ordinal.get(piece.ordinal)
        context = make_context(doc_title, piece_heading)
        if existing is not None and existing.content_hash == piece_hash:
            embedding_changed = existing.context != context
            existing.kind = kind
            existing.topic_id = topic_id
            existing.concept_id = concept_id
            existing.heading = piece_heading
            existing.context = context
            existing.meta = dict(metadata)
            existing.source_mtime = source_mtime
            session.add(existing)
            embedder = getattr(retriever, "embedder", None)
            if embedding_changed or (
                embedder is not None and existing.embedding_model != embedder.name
            ):
                changed_chunks.append(existing)
            active_chunks.append(existing)
            skipped += 1
            continue

        if existing is None:
            existing = Chunk(
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
            session.add(existing)
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
        changed_chunks.append(existing)
        active_chunks.append(existing)
        indexed += 1

    orphans = [chunk for chunk in existing_chunks if chunk.ordinal >= len(pieces)]
    _delete_chunk_concept_rows(session, orphans)
    for chunk in orphans:
        session.delete(chunk)
    session.flush()

    names = concept_name_index(session, topic_id) if topic_id is not None else []
    for chunk in active_chunks:
        tag_chunk_concepts(session, chunk, names)

    on_index = getattr(retriever, "on_index", None)
    if callable(on_index):
        session.flush()
        changed_ids = [chunk.id for chunk in changed_chunks if chunk.id is not None]
        try:
            with session.begin_nested():
                on_index(session, changed_ids)
        except Exception as exc:
            for chunk in changed_chunks:
                chunk.embedding_model = None
                session.add(chunk)
            session.add(
                AgentEvent(
                    topic_id=topic_id,
                    kind="memory:error",
                    detail=f"embed: {type(exc).__name__}: {exc}"[:400],
                )
            )

    return IndexResult(indexed=indexed, skipped=skipped, removed=len(orphans))


def remove_source(session: Session, source_ref: str) -> int:
    """Delete every chunk for one source without committing the session."""
    chunks = session.exec(select(Chunk).where(Chunk.source_ref == source_ref)).all()
    _delete_chunk_concept_rows(session, chunks)
    for chunk in chunks:
        session.delete(chunk)
    return len(chunks)


def topic_id_for_concept(session: Session, concept_id: int) -> int:
    """Resolve the owning topic for one persisted concept."""
    concept = session.get(Concept, concept_id)
    if concept is None:
        raise ValueError("concept not found")
    track = session.get(Track, concept.track_id)
    if track is None:
        raise ValueError("concept track not found")
    return track.topic_id


def index_message(
    session: Session,
    msg: Message,
    *,
    concept_id: int,
    topic_id: int,
    levels: Levels | None = None,
    retriever: Retriever | None = None,
) -> IndexResult:
    """Index one persisted learner or tutor conversation message."""
    if msg.id is None:
        raise ValueError("message must be flushed before indexing")
    source_ref = f"message:{msg.id}"
    if msg.role == "user":
        return index_text(
            session,
            kind="learner_output",
            text=msg.content,
            source_ref=source_ref,
            topic_id=topic_id,
            concept_id=concept_id,
            retriever=retriever,
        )
    if msg.role == "tutor" and len(msg.content) >= TUTOR_TURN_MIN_CHARS:
        metadata = {}
        if levels is not None:
            metadata = {
                "assistance": levels.assistance,
                "challenge": levels.challenge,
            }
        return index_text(
            session,
            kind="tutor_turn",
            text=msg.content,
            source_ref=source_ref,
            topic_id=topic_id,
            concept_id=concept_id,
            meta=metadata,
            retriever=retriever,
        )

    removed = remove_source(session, source_ref)
    return IndexResult(indexed=0, skipped=0, removed=removed)


def index_assessment(
    session: Session,
    a: Assessment,
    *,
    topic_id: int,
    retriever: Retriever | None = None,
) -> IndexResult:
    """Index an assessment prompt and the learner response as separate sources."""
    if a.id is None:
        raise ValueError("assessment must be flushed before indexing")
    question = index_text(
        session,
        kind="question",
        text=a.prompt,
        source_ref=f"assessment:{a.id}#q",
        topic_id=topic_id,
        concept_id=a.concept_id,
        retriever=retriever,
    )
    response = index_text(
        session,
        kind="learner_output",
        text=a.response,
        source_ref=f"assessment:{a.id}#r",
        topic_id=topic_id,
        concept_id=a.concept_id,
        meta={
            "assessment_kind": a.kind,
            "score": a.score,
            "verdict": a.verdict,
        },
        retriever=retriever,
    )
    return _combine_index_results(question, response)


def index_roleplay_turn(
    session: Session,
    t: RoleplayTurn,
    *,
    topic_id: int,
    concept_ids: Iterable[int],
    retriever: Retriever | None = None,
) -> IndexResult:
    """Index one learner or persona roleplay turn."""
    if t.id is None:
        raise ValueError("roleplay turn must be flushed before indexing")
    kind_by_role = {"user": "learner_output", "persona": "tutor_turn"}
    kind = kind_by_role.get(t.role)
    source_ref = f"roleplayturn:{t.id}"
    if kind is None:
        removed = remove_source(session, source_ref)
        return IndexResult(indexed=0, skipped=0, removed=removed)
    return index_text(
        session,
        kind=kind,
        text=t.content,
        source_ref=source_ref,
        topic_id=topic_id,
        concept_id=_single_concept_id(concept_ids),
        retriever=retriever,
    )


def index_question(
    session: Session,
    *,
    text: str,
    source_ref: str,
    topic_id: int | None,
    concept_id: int | None,
    retriever: Retriever | None = None,
) -> IndexResult:
    """Index one generated question."""
    return index_text(
        session,
        kind="question",
        text=text,
        source_ref=source_ref,
        topic_id=topic_id,
        concept_id=concept_id,
        retriever=retriever,
    )


def index_paper_answer(
    session: Session,
    answer: PaperProbeAnswer,
    *,
    topic_id: int,
    concept_ids: Iterable[int],
    role: str = "",
    retriever: Retriever | None = None,
) -> IndexResult:
    """Index one persisted paper-probe answer."""
    if answer.id is None:
        raise ValueError("paper answer must be flushed before indexing")
    metadata = {"role": role} if role else None
    return index_text(
        session,
        kind="learner_output",
        text=answer.content,
        source_ref=f"paperprobe:{answer.probe_id}#{answer.question_index}",
        topic_id=topic_id,
        concept_id=_single_concept_id(concept_ids),
        meta=metadata,
        retriever=retriever,
    )


def _single_concept_id(concept_ids: Iterable[int]) -> int | None:
    unique_ids = list(dict.fromkeys(concept_ids))
    return unique_ids[0] if len(unique_ids) == 1 else None


def _combine_index_results(*results: IndexResult) -> IndexResult:
    return IndexResult(
        indexed=sum(result.indexed for result in results),
        skipped=sum(result.skipped for result in results),
        removed=sum(result.removed for result in results),
    )


def index_source_doc(
    session: Session,
    doc: SourceDoc,
    *,
    fetch: Callable[[str], str | None] = fetch_artifact_text,
    retriever: Retriever | None = None,
) -> IndexResult:
    """Fetch and index one accepted source without changing the source row."""
    if doc.id is None:
        raise ValueError("source document must be flushed before indexing")

    if doc.url.startswith("file://"):
        vault_chunks = session.exec(
            select(Chunk).where(
                Chunk.kind == "vault_note",
                Chunk.source_ref == doc.url,
            )
        ).all()
        if vault_chunks:
            return IndexResult(indexed=0, skipped=len(vault_chunks), removed=0)

    try:
        text = fetch(doc.url)
    except Exception as exc:
        _add_memory_event(
            session,
            kind="memory:fetch_skipped",
            detail=f"sourcedoc:{doc.id} {type(exc).__name__}: {exc}",
            event_target={"topic_id": doc.topic_id},
        )
        return IndexResult(indexed=0, skipped=1, removed=0)

    if not text or not text.strip():
        _add_memory_event(
            session,
            kind="memory:fetch_skipped",
            detail=f"sourcedoc:{doc.id} empty response",
            event_target={"topic_id": doc.topic_id},
        )
        return IndexResult(indexed=0, skipped=1, removed=0)

    return index_text(
        session,
        kind="source_doc",
        text=text,
        source_ref=f"sourcedoc:{doc.id}",
        topic_id=doc.topic_id,
        heading=doc.title,
        retriever=retriever,
    )


def index_paper(
    session: Session,
    pp: PaperProbe,
    *,
    retriever: Retriever | None = None,
) -> IndexResult:
    """Index a paper probe under the milestone's first materialized topic."""
    if pp.id is None:
        raise ValueError("paper probe must be flushed before indexing")

    topic_id = None
    links = session.exec(
        select(ProgramTopicLink)
        .where(ProgramTopicLink.milestone_id == pp.milestone_id)
        .order_by(ProgramTopicLink.id)
    ).all()
    for link in links:
        if link.topic_id is not None:
            topic_id = link.topic_id
            break

    return index_text(
        session,
        kind="paper",
        text=pp.paper_text,
        source_ref=f"paperprobe:{pp.id}",
        doc_title=pp.paper_title,
        topic_id=topic_id,
        meta={
            "arxiv_id": _arxiv_id(pp.paper_url),
            "url": pp.paper_url,
            "title": pp.paper_title,
        },
        splitter=split_markdown,
        retriever=retriever,
    )


def _arxiv_id(url: str) -> str:
    """New-style arXiv id from an arxiv.org URL; "" for any other host."""
    from urllib.parse import urlsplit

    from adaptive_academy.engine.paper import _ARXIV_ID_RE

    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if not (host == "arxiv.org" or host.endswith(".arxiv.org")):
        return ""
    match = _ARXIV_ID_RE.search(parts.path)
    return match.group(1) if match else ""


def reindex_topic(
    session: Session,
    topic_id: int,
    *,
    vault_path: str,
    fetch: Callable[[str], str | None],
    kinds: tuple[str, ...] = REINDEX_KINDS,
    deadline_s: float = REINDEX_DEADLINE_S,
    vault_only_refs: set[str] | None = None,
    retriever: Retriever | None = None,
    progress: dict[str, int] | None = None,
) -> ReindexResult:
    """Reindex one topic and return partial counts when the deadline expires.

    ``progress`` (indexed/skipped/removed) is bumped after every committed unit so a caller
    can report work that was already persisted if a later unit raises.

    ``vault_only_refs`` restricts the vault sweep to notes this topic already owns.
    """
    from adaptive_academy.engine.vault import reindex_vault

    started = time.perf_counter()
    deadline = started + max(deadline_s, 0)
    indexed = 0
    skipped = 0
    removed = 0
    truncated = False
    selected = set(kinds)

    if "vault_note" in selected:
        if time.perf_counter() >= deadline:
            truncated = True
        else:
            result = reindex_vault(
                session,
                topic_id,
                vault_path,
                only_refs=vault_only_refs,
                retriever=retriever,
                progress=progress,
                deadline=deadline,
            )
            indexed += result.indexed
            skipped += result.skipped
            removed += result.removed
            truncated = result.truncated

    if "source_doc" in selected and not truncated:
        source_chunks = session.exec(
            select(Chunk).where(
                Chunk.kind == "source_doc",
                Chunk.topic_id == topic_id,
            )
        ).all()
        stale_refs: set[str] = set()
        for chunk in source_chunks:
            prefix, separator, raw_id = chunk.source_ref.partition(":")
            try:
                source_id = int(raw_id) if prefix == "sourcedoc" and separator else None
            except ValueError:
                source_id = None
            source = session.get(SourceDoc, source_id) if source_id is not None else None
            if source is None or source.status != "accepted":
                stale_refs.add(chunk.source_ref)
        for source_ref in sorted(stale_refs):
            removed += remove_source(session, source_ref)

        docs = session.exec(
            select(SourceDoc)
            .where(
                SourceDoc.topic_id == topic_id,
                SourceDoc.status == "accepted",
            )
            .order_by(SourceDoc.id)
        ).all()
        for doc in docs:
            if time.perf_counter() >= deadline:
                truncated = True
                break
            result = index_source_doc(session, doc, fetch=fetch, retriever=retriever)
            indexed += result.indexed
            skipped += result.skipped
            removed += result.removed
            session.commit()
            bump_progress(progress, indexed=result.indexed, skipped=result.skipped, removed=result.removed)

    reembed_truncated = _reembed_stale_chunks(
        session,
        retriever,
        topic_id=topic_id,
        deadline=deadline,
    )
    truncated = truncated or reembed_truncated

    elapsed_ms = int((time.perf_counter() - started) * 1000)
    session.add(
        AgentEvent(
            topic_id=topic_id,
            kind="memory:reindex_topic",
            detail=(
                f"kinds={','.join(kinds)} indexed={indexed} skipped={skipped} "
                f"removed={removed} truncated={str(truncated).lower()} ms={elapsed_ms}"
            ),
        )
    )
    session.commit()
    return ReindexResult(
        indexed=indexed,
        skipped=skipped,
        removed=removed,
        truncated=truncated,
        ms=elapsed_ms,
    )


def _reembed_stale_chunks(
    session: Session,
    retriever: Retriever | None,
    *,
    topic_id: int,
    deadline: float,
) -> bool:
    """Refresh stale vectors in bounded batches and report deadline truncation."""
    on_index = getattr(retriever, "on_index", None)
    if not callable(on_index):
        return False

    embedder = getattr(retriever, "embedder", None)
    if embedder is None:
        return False

    chunks = session.exec(
        select(Chunk)
        .where(
            Chunk.topic_id == topic_id,
            or_(
                col(Chunk.embedding_model).is_(None),
                Chunk.embedding_model != embedder.name,
            ),
        )
        .order_by(Chunk.id)
    ).all()
    for start in range(0, len(chunks), 64):
        if time.perf_counter() >= deadline:
            return True
        batch = chunks[start : start + 64]
        chunk_ids = [chunk.id for chunk in batch if chunk.id is not None]
        try:
            with session.begin_nested():
                on_index(session, chunk_ids)
        except Exception as exc:
            for chunk in batch:
                chunk.embedding_model = None
                session.add(chunk)
            session.add(
                AgentEvent(
                    topic_id=topic_id,
                    kind="memory:error",
                    detail=f"embed: {type(exc).__name__}: {exc}"[:400],
                )
            )
        session.commit()
    return False


def jaccard(a: str, b: str) -> float:
    """Return Jaccard similarity over case-folded normalized token sets."""
    a_tokens = set(normalize(a).casefold().split())
    b_tokens = set(normalize(b).casefold().split())
    union = a_tokens | b_tokens
    if not union:
        return 0.0
    return len(a_tokens & b_tokens) / len(union)


def escape_markers(text: str) -> str:
    """Neutralize prompt-block delimiter sequences in untrusted text."""
    return text.replace("<<<", "‹‹‹").replace(">>>", "›››")


def render_block(
    hits: list[Hit],
    *,
    marker: str,
    budget: int = INJECT_BUDGET_CHARS,
) -> str:
    """Render complete retrieved chunks within a strict character budget."""
    marker_name = marker.strip().strip("<>")
    if marker_name.startswith("END_"):
        marker_name = marker_name[4:]
    if not hits or not marker_name or budget <= 0:
        return ""

    opening = f"<<<{marker_name}>>>"
    closing = f"<<<END_{marker_name}>>>"
    entries: list[str] = []
    for hit in hits:
        lines = [escape_markers(_provenance_line(hit))]
        if hit.chunk.context:
            lines.append(escape_markers(hit.chunk.context))
        lines.append(escape_markers(hit.chunk.text))
        entry = "\n".join(lines)
        candidate = f"{opening}\n{'\n\n'.join([*entries, entry])}\n{closing}"
        if len(candidate) > budget:
            break
        entries.append(entry)
    if not entries:
        return ""
    return f"{opening}\n{'\n\n'.join(entries)}\n{closing}"


def _provenance_line(hit: Hit) -> str:
    chunk = hit.chunk
    meta = chunk.meta or {}
    parts = [chunk.kind]
    assessment_kind = str(meta.get("assessment_kind", "")).strip()
    role = str(meta.get("role", "")).strip()
    if assessment_kind:
        parts.append(assessment_kind)
    elif role:
        parts.append(role)
    if meta.get("score") is not None:
        parts.append(f"score {meta['score']}")
    arxiv_id = str(meta.get("arxiv_id", "")).strip()
    if arxiv_id:
        parts.append(f"arXiv:{arxiv_id}")
    if chunk.heading:
        heading = f"§ {chunk.heading}" if chunk.kind == "paper" else chunk.heading
        parts.append(heading)
    if chunk.kind in {"learner_output", "tutor_turn", "question"}:
        parts.append(chunk.created_at.date().isoformat())
    return f"[{' · '.join(parts)}]"


def append_block_entry(
    block: str,
    text: str,
    *,
    marker: str,
    label: str,
    budget: int = INJECT_BUDGET_CHARS,
) -> str:
    """Append one complete generated entry, falling back to that entry alone."""
    marker_name = marker.strip().strip("<>")
    if marker_name.startswith("END_"):
        marker_name = marker_name[4:]
    opening = f"<<<{marker_name}>>>"
    closing = f"<<<END_{marker_name}>>>"
    entry = f"[{escape_markers(label)}]\n{escape_markers(text)}"
    if block.endswith(closing):
        candidate = f"{block[:-len(closing)].rstrip()}\n\n{entry}\n{closing}"
    else:
        candidate = f"{opening}\n{entry}\n{closing}"
    if len(candidate) <= budget:
        return candidate
    fallback = f"{opening}\n{entry}\n{closing}"
    return fallback if len(fallback) <= budget else block


def memory_blocks_for_tutor(
    session: Session,
    retriever: Retriever,
    convo: Conversation,
    concept: Concept,
    user_text: str,
) -> tuple[str, str, list[Hit]]:
    """Build tutor grounding and anti-repeat blocks for one conversation turn."""
    if concept.id is None:
        return "", "", []
    messages = session.exec(
        select(Message).where(Message.conversation_id == convo.id)
    ).all()
    excluded = tuple(
        f"message:{message.id}" for message in messages if message.id is not None
    )
    query = f"{concept.name} {user_text}".strip()
    target = {"conversation_id": convo.id}
    grounding_hits = retrieve(
        session,
        retriever,
        query,
        kinds=("vault_note", "source_doc", "paper"),
        concept_id=concept.id,
        k=TUTOR_GROUNDING_K,
        expand_links=True,
        event_target=target,
    )
    tutor_hits = retrieve(
        session,
        retriever,
        query,
        kinds=("tutor_turn",),
        concept_id=concept.id,
        k=TUTOR_COVERED_K,
        exclude_source_refs=excluded,
        order="recency",
        event_target=target,
    )
    learner_hits = retrieve(
        session,
        retriever,
        query,
        kinds=("learner_output",),
        concept_id=concept.id,
        k=TUTOR_COVERED_K,
        exclude_source_refs=excluded,
        order="recency",
        event_target=target,
    )
    covered_hits = [*tutor_hits, *learner_hits]
    return (
        render_block(grounding_hits, marker=MEMORY_MARKER),
        render_block(covered_hits, marker=ALREADY_COVERED_MARKER),
        [*grounding_hits, *covered_hits],
    )


def avoid_block_for_concepts(
    session: Session,
    retriever: Retriever,
    concept_ids: Iterable[int],
    *,
    k: int = AVOID_K,
) -> tuple[str, list[Hit]]:
    """Retrieve and render prior questions across one or more concepts."""
    hits: list[Hit] = []
    for concept_id in dict.fromkeys(concept_ids):
        concept = session.get(Concept, concept_id)
        if concept is None:
            continue
        hits.extend(
            retrieve(
                session,
                retriever,
                concept.name,
                kinds=("question",),
                concept_id=concept_id,
                k=k,
                event_target={"topic_id": topic_id_for_concept(session, concept_id)},
            )
        )

    ranked = sorted(
        hits,
        key=lambda hit: (
            -hit.score,
            -_datetime_key(hit.chunk.created_at),
            hit.chunk.id or 0,
        ),
    )
    unique: list[Hit] = []
    hashes: set[str] = set()
    for hit in ranked:
        if len(unique) >= max(k, 0):
            break
        if hit.chunk.content_hash in hashes:
            continue
        hashes.add(hit.chunk.content_hash)
        unique.append(hit)
    return render_block(unique, marker=ALREADY_COVERED_MARKER), unique


def is_near_duplicate(
    text: str,
    hits: list[Hit],
    *,
    threshold: float = NEARDUP_JACCARD,
    embedder: Embedder | None = None,
    cosine_threshold: float = NEARDUP_COSINE,
) -> Hit | None:
    """Return the first prior chunk meeting the Jaccard or cosine threshold."""
    for hit in hits:
        if jaccard(text, hit.chunk.text) >= threshold:
            return hit

    if embedder is None or not hits:
        return None
    try:
        vectors = embedder.embed([text, *(hit.chunk.text for hit in hits)])
        if len(vectors) != len(hits) + 1:
            return None
        query_vector = vectors[0]
        for hit, vector in zip(hits, vectors[1:], strict=True):
            if _cosine_similarity(query_vector, vector) >= cosine_threshold:
                return hit
    except Exception:
        return None
    return None


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if len(a) != len(b) or not a:
        return 0.0
    a_magnitude = math.sqrt(sum(value * value for value in a))
    b_magnitude = math.sqrt(sum(value * value for value in b))
    if a_magnitude == 0.0 or b_magnitude == 0.0:
        return 0.0
    return sum(left * right for left, right in zip(a, b, strict=True)) / (
        a_magnitude * b_magnitude
    )


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
    """Retrieve direct hits, then append zero-score link hits into open slots."""
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
        limit = max(k, 0)
        search_k = limit * 3
        ranked = retriever.search(session, expanded_query, where=where, k=search_k)
        candidates = _load_ranked_chunks(session, ranked, where=where)
        if order == "recency":
            candidates.sort(
                key=lambda hit: (_datetime_key(hit.chunk.created_at), hit.score),
                reverse=True,
            )
        direct_hits = _deduplicate_hits(candidates, limit=limit)
        link_hits: list[Hit] = []
        if expand_links and len(direct_hits) < limit:
            linked_source_refs = _linked_source_refs(session, direct_hits)
        else:
            linked_source_refs = []
        if linked_source_refs:
            link_where = replace(where, source_refs=tuple(linked_source_refs))
            link_ranked = retriever.search(
                session,
                expanded_query,
                where=link_where,
                k=max(len(linked_source_refs) * 3, limit * 3),
            )
            link_candidates = _load_ranked_chunks(session, link_ranked, where=link_where)
            best_by_source: dict[str, Hit] = {}
            for candidate in link_candidates:
                source_ref = candidate.chunk.source_ref
                current = best_by_source.get(source_ref)
                if current is None or candidate.score > current.score:
                    best_by_source[source_ref] = candidate
            for source_ref in linked_source_refs:
                candidate = best_by_source.get(source_ref)
                if candidate is None:
                    chunk = session.exec(
                        select(Chunk)
                        .where(
                            Chunk.source_ref == source_ref,
                            Chunk.ordinal == 0,
                        )
                        .order_by(Chunk.id)
                    ).first()
                    if chunk is None or not _matches_filter(chunk, link_where):
                        continue
                    candidate = Hit(chunk=chunk, score=0.0)
                link_hits.append(Hit(chunk=candidate.chunk, score=0.0, via="link"))

        hits = _deduplicate_hits([*direct_hits, *link_hits], limit=limit)
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


def _linked_source_refs(
    session: Session,
    direct_hits: list[Hit],
) -> list[str]:
    linked_source_refs: list[str] = []
    seen_source_refs = {hit.chunk.source_ref for hit in direct_hits}

    for direct_hit in direct_hits:
        if direct_hit.chunk.kind != "vault_note":
            continue
        links = session.exec(
            select(VaultLink)
            .where(
                VaultLink.src_ref == direct_hit.chunk.source_ref,
                VaultLink.dst_ref != "",
            )
            .order_by(VaultLink.id)
        ).all()
        for link in links:
            if link.dst_ref in seen_source_refs:
                continue
            seen_source_refs.add(link.dst_ref)
            linked_source_refs.append(link.dst_ref)
    return linked_source_refs


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
