"""Pure text chunking and indexing helpers for local memory retrieval."""

import hashlib
import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from sqlmodel import Session, select

from adaptive_academy.engine.vault import parse_frontmatter
from adaptive_academy.models import Chunk

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


def normalize(text: str) -> str:
    """Return NFC text with leading, trailing, and repeated whitespace removed."""
    normalized = unicodedata.normalize("NFC", text)
    return re.sub(r"\s+", " ", normalized).strip()


def content_hash(text: str) -> str:
    """Return a stable hash for text after normalization."""
    return hashlib.sha256(normalize(text).encode("utf-8")).hexdigest()


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
