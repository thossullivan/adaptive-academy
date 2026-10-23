"""Obsidian vault integration — pure core (slugs, frontmatter, scanning, path-safety, renderers).

A vault is a folder of markdown on disk; everything here is local file I/O or pure string work,
honoring local-first (no external services, no data egress). Orchestration that touches the DB
lives in the API layer; this module stays side-effect-light and unit-testable.
"""

from __future__ import annotations

import io
import os
import re
import stat
import time
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from sqlmodel import Session, col, select

from adaptive_academy.engine.assess import GRADING_KINDS, graded_concept_ids, level_from_score
from adaptive_academy.engine.track_markdown import (
    DeliverableView,
    ItemView,
    PhaseView,
    SidebarView,
    TrackView,
    track_to_markdown,
)
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Chunk,
    Concept,
    Deliverable,
    Item,
    KnowledgeEstimate,
    Phase,
    Sidebar,
    SourceDoc,
    Topic,
    Track,
    VaultLink,
)

if TYPE_CHECKING:
    from adaptive_academy.engine.memory import IndexResult
    from adaptive_academy.llm.retriever_types import Retriever

# We own this subfolder for exports; ingest skips it to avoid a feedback loop.
EXPORT_FOLDER = "Adaptive Academy"
_SUMMARY_CAP = 280
_MAX_SCAN_FILES = 2000
_MAX_READ_CHARS = 100_000  # only the head is needed for title/summary
_HAS_DESCRIPTOR_WALK = (
    os.open in os.supports_dir_fd
    and hasattr(os, "O_DIRECTORY")
    and hasattr(os, "O_NOFOLLOW")
)


def slugify(name: str) -> str:
    """A file-name slug that keeps letters and digits in any script ("微积分" stays, "Café"
    becomes "café"); everything else, underscores included, becomes one "-". ASCII names
    slug as before. Can be "" (a name of only symbols, like "C++" minus its letter: callers
    fall back to an id-based name)."""
    text = unicodedata.normalize("NFKC", name or "").casefold()
    return re.sub(r"[\W_]+", "-", text).strip("-")


def legacy_slugify(name: str) -> str:
    """The ASCII-only slug exports used before slugify kept other scripts ("Cálculo" was
    "c-lculo"): an existing note or folder under it is reused, not copied."""
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


# --- frontmatter -------------------------------------------------------------

def render_frontmatter(data: dict) -> str:
    lines = ["---"]
    for k, v in data.items():
        if isinstance(v, (list, tuple)):
            lines.append(f"{k}: [{', '.join(str(x) for x in v)}]")
        else:
            lines.append(f"{k}: {v}")
    lines.append("---\n")
    return "\n".join(lines)


def parse_frontmatter(md: str) -> tuple[dict, str]:
    """Minimal frontmatter parser: returns (scalar dict, body). Lists/quotes left as raw text."""
    if not md.startswith("---\n"):
        return {}, md
    end = md.find("\n---", 4)
    if end == -1:
        return {}, md
    block = md[4:end]
    body = md[end + 4 :]
    if body.startswith("\n"):
        body = body[1:]
    fm: dict = {}
    for line in block.splitlines():
        if ":" in line:
            k, _, val = line.partition(":")
            fm[k.strip()] = val.strip()
    return fm, body


def note_title(md: str, fallback: str) -> str:
    fm, body = parse_frontmatter(md)
    if fm.get("title"):
        return fm["title"]
    for line in body.splitlines():
        m = re.match(r"#\s+(.*)", line.strip())
        if m:
            return m.group(1).strip()
    return fallback


def note_summary(md: str, cap: int = _SUMMARY_CAP) -> str:
    fm, body = parse_frontmatter(md)
    if fm.get("summary"):
        return _cap(fm["summary"], cap)
    for para in re.split(r"\n\s*\n", body):
        text = " ".join(
            ln.strip() for ln in para.splitlines() if ln.strip() and not ln.lstrip().startswith("#")
        ).strip()
        if text:
            return _cap(text, cap)
    return ""


def _cap(text: str, cap: int) -> str:
    text = text.strip()
    return text if len(text) <= cap else text[:cap].rstrip() + "…"


# --- scanning + path-safety --------------------------------------------------

def _is_safe_vault_path(path: Path, vault: Path) -> bool:
    """Return whether a non-symlink path resolves inside the vault."""
    if path.is_symlink():
        return False
    try:
        resolved = path.resolve(strict=True)
    except OSError:
        return False
    root = vault.resolve()
    return resolved == root or root in resolved.parents


def _inside_skipped(root: Path, vault: Path, skip_dirs: frozenset[str]) -> bool:
    try:
        relative = root.resolve().relative_to(vault.resolve())
    except ValueError:
        return False
    return any(part in skip_dirs for part in relative.parts)


def _scan_notes_with_skips(
    root: Path,
    *,
    vault: Path,
    skip_dirs: frozenset[str] = frozenset({EXPORT_FOLDER}),
    deadline: float | None = None,
) -> tuple[list[Path], list[Path], bool]:
    """List safe notes, rejected paths, and whether the scan reached its end.

    The scan stops (complete=False) at the file cap or when the absolute deadline passes.
    A root at or inside a skipped export folder (a subfolder of "Adaptive Academy/...") lists
    nothing: the app's own notes are never read back as the learner's.
    """
    notes: list[Path] = []
    rejected: list[Path] = []
    if _inside_skipped(root, vault, skip_dirs):
        return notes, rejected, True
    for directory, dirnames, filenames in os.walk(root, followlinks=False):
        if deadline is not None and time.perf_counter() >= deadline:
            return sorted(notes), sorted(rejected), False
        directory_path = Path(directory)
        retained_dirs: list[str] = []
        for name in sorted(dirnames):
            child = directory_path / name
            if child.is_symlink() or not _is_safe_vault_path(child, vault):
                rejected.append(child)
            elif name not in skip_dirs and not name.startswith("."):
                retained_dirs.append(name)
        dirnames[:] = retained_dirs

        for name in sorted(filenames):
            if not name.endswith(".md"):
                continue
            path = directory_path / name
            if path.is_symlink() or not _is_safe_vault_path(path, vault):
                rejected.append(path)
                continue
            notes.append(path)
            if len(notes) > _MAX_SCAN_FILES:
                return sorted(notes[:_MAX_SCAN_FILES]), sorted(rejected), False
    return sorted(notes), sorted(rejected), True


def scan_notes(root: Path, *, skip_dirs: frozenset[str] = frozenset({EXPORT_FOLDER})) -> list[Path]:
    """Recursively list `*.md` under root, skipping our export folder and dotfolders."""
    resolved_root = root.resolve()
    notes, _, _ = _scan_notes_with_skips(
        resolved_root,
        vault=resolved_root,
        skip_dirs=skip_dirs,
    )
    return notes


def _frontmatter_list(value: object) -> list[str]:
    if not value:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    raw = str(value).strip()
    if raw.startswith("[") and raw.endswith("]"):
        raw = raw[1:-1]
    values = []
    for item in raw.split(","):
        cleaned = item.strip().strip("'\"")
        if cleaned:
            values.append(cleaned)
    return values


def _read_text(
    path: Path,
    *,
    vault: Path,
    limit: int,
    errors: str,
    newline: str | None = None,
) -> str:
    """Read a vault note without following symlinks. `newline=""` keeps the file's own line
    endings (the notebook sync writes the note back and must not change them)."""
    if _HAS_DESCRIPTOR_WALK:
        return _read_text_descriptor(
            path,
            vault=vault,
            limit=limit,
            errors=errors,
            newline=newline,
        )

    return _read_text_fallback(
        path,
        vault=vault,
        limit=limit,
        errors=errors,
        newline=newline,
    )


def _read_text_descriptor(
    path: Path,
    *,
    vault: Path,
    limit: int,
    errors: str,
    newline: str | None = None,
) -> str:
    root = vault.resolve()
    try:
        relative = path.relative_to(root)
    except ValueError as exc:
        raise OSError("outside-vault-or-symlink") from exc
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise OSError("outside-vault-or-symlink")

    # O_NOFOLLOW on the root refuses a root swapped for a symlink between resolve() and
    # open(); the fstat check refuses anything that is not a directory.
    root_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        root_flags |= os.O_CLOEXEC
    descriptor = os.open(root, root_flags)
    try:
        if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
            raise OSError("outside-vault-or-symlink")
        for index, name in enumerate(relative.parts):
            flags = os.O_RDONLY | os.O_NOFOLLOW
            if index < len(relative.parts) - 1:
                flags |= os.O_DIRECTORY
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            child_descriptor = os.open(name, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child_descriptor
        final_stat = os.fstat(descriptor)
        if not stat.S_ISREG(final_stat.st_mode):
            raise OSError("outside-vault-or-symlink")
        final_descriptor = descriptor
        descriptor = -1
        with os.fdopen(final_descriptor, "rb") as raw:
            with io.TextIOWrapper(raw, encoding="utf-8", errors=errors,
                                  newline=newline) as handle:
                text = handle.read(limit)
        _LAST_READ_MTIME[path] = final_stat.st_mtime
        return text
    finally:
        if descriptor >= 0:
            os.close(descriptor)


# mtime observed on the descriptor that was actually read (same object as the text),
# so callers never stat the path a second time and race a swap.
_LAST_READ_MTIME: dict[Path, float] = {}


def _read_index_text_with_mtime(path: Path, *, vault: Path) -> tuple[str, float]:
    """Read a vault note and return (text, mtime) from the very descriptor that was read."""
    _LAST_READ_MTIME.pop(path, None)
    text = _read_index_text(path, vault=vault)
    mtime = _LAST_READ_MTIME.pop(path, None)
    if mtime is None:
        mtime = path.stat(follow_symlinks=False).st_mtime
    return text, mtime


def _read_text_fallback(
    path: Path,
    *,
    vault: Path,
    limit: int,
    errors: str,
    newline: str | None = None,
) -> str:
    if not _is_safe_vault_path(path, vault):
        raise OSError("outside-vault-or-symlink")

    nofollow = getattr(os, "O_NOFOLLOW", None)
    if nofollow is None:
        with path.open(encoding="utf-8", errors=errors, newline=newline) as handle:
            return handle.read(limit)

    flags = os.O_RDONLY | nofollow
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    descriptor = os.open(path, flags)
    with os.fdopen(descriptor, encoding="utf-8", errors=errors, newline=newline) as handle:
        return handle.read(limit)


def _read_index_text(path: Path, *, vault: Path) -> str:
    from adaptive_academy.engine.memory import MAX_INDEX_CHARS

    return _read_text(
        path,
        vault=vault,
        limit=MAX_INDEX_CHARS,
        errors="strict",
    )


def build_title_index(
    root: Path | str,
    *,
    deadline: float | None = None,
) -> dict[str, str]:
    """Build a case-folded title and frontmatter-alias map for one vault sweep."""
    titles, _complete = build_title_index_checked(root, deadline=deadline)
    return titles


def build_title_index_checked(
    root: Path | str,
    *,
    deadline: float | None = None,
) -> tuple[dict[str, str], bool]:
    """Title index plus whether it is complete (deadline and file cap honoured in the scan)."""
    resolved_root = Path(root).resolve()
    titles: dict[str, str] = {}
    paths, _rejected, complete = _scan_notes_with_skips(
        resolved_root, vault=resolved_root, deadline=deadline
    )
    for path in paths:
        if deadline is not None and time.perf_counter() >= deadline:
            complete = False
            break
        try:
            text = _read_index_text(path, vault=resolved_root)
        except (OSError, UnicodeError):
            # An unreadable note leaves the index partial: callers must not resolve links
            # against it (a link to this note would silently degrade to unresolved).
            complete = False
            continue
        frontmatter, _ = parse_frontmatter(text)
        names = [note_title(text, path.stem), *_frontmatter_list(frontmatter.get("aliases"))]
        for name in names:
            key = name.strip().casefold()
            if key:
                titles.setdefault(key, path.resolve().as_uri())
    return titles, complete


def safe_vault_dir(path: str) -> Path:
    if not path or not path.strip():
        raise ValueError("vault path is empty")
    resolved = Path(path).expanduser().resolve()
    if not resolved.exists():
        raise ValueError(f"vault path does not exist: {resolved}")
    if not resolved.is_dir():
        raise ValueError(f"vault path is not a directory: {resolved}")
    return resolved


def safe_child(vault: Path, *parts: str) -> Path:
    """Join parts under the resolved vault root, refusing anything that escapes it."""
    root = vault.resolve()
    child = root.joinpath(*parts).resolve()
    if root != child and root not in child.parents:
        raise ValueError(f"path escapes the vault root: {child}")
    return child


# --- entity → markdown renderers (pure; DB extraction happens in the caller) --

def render_hub_note(
    topic_title: str, overview: str, track_markdown: str, concept_names: list[str],
    *, concept_stems: list[str] | None = None, topic_id: int | None = None,
) -> str:
    """`concept_stems`: each concept note's file name (without .md), in the same order as
    `concept_names`, when it differs from the plain slug (engine/notebook_sync.py
    disambiguates names that slug alike). `topic_id` marks the hub as this topic's."""
    data: dict = {"title": topic_title, "tags": ["adaptive-academy"]}
    if topic_id is not None:
        data["topic_id"] = topic_id
    fm = render_frontmatter(data)
    parts = [fm, f"# {topic_title}\n"]
    if overview:
        parts.append(overview + "\n")
    if concept_names:
        stems = concept_stems or [slugify(n) for n in concept_names]
        parts.append("## Concepts\n")
        parts.append(
            "\n".join(f"- [[{stem}|{n}]]" for stem, n in zip(stems, concept_names, strict=True))
            + "\n"
        )
    if track_markdown:
        parts.append("## Track\n")
        parts.append(track_markdown)
    return "\n".join(parts).rstrip() + "\n"


def render_concept_note(
    name: str, verdict: str, load_bearing: bool, summary: str, hub_slug: str
) -> str:
    fm = render_frontmatter(
        {
            "title": name,
            "tags": ["adaptive-academy", "concept"],
            "verdict": verdict,
            "load_bearing": "true" if load_bearing else "false",
        }
    )
    parts = [fm, f"# {name}\n", f"**Verdict:** {verdict}\n"]
    if summary:
        parts.append(summary + "\n")
    parts.append(f"Part of [[{hub_slug}]].")
    return "\n".join(parts).rstrip() + "\n"


# --- orchestration (DB <-> files) --------------------------------------------

@dataclass
class IngestResult:
    count: int
    titles: list[str] = field(default_factory=list)


@dataclass
class ExportResult:
    written: list[str] = field(default_factory=list)
    # Concept notes left as they were, with why (engine/notebook_sync.py: unbalanced
    # notebook markers, a symlink, a note too large to update safely).
    problems: list[str] = field(default_factory=list)


@dataclass
class ExportAllResult:
    topics: int
    written: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)


def _sync_vault_links(
    session: Session,
    source_ref: str,
    text: str,
    title_index: dict[str, str],
) -> None:
    from adaptive_academy.engine.memory import extract_wikilinks

    desired = [
        (title_index.get(link.target.casefold(), ""), link.target)
        for link in extract_wikilinks(text)
    ]
    existing = session.exec(
        select(VaultLink).where(VaultLink.src_ref == source_ref).order_by(VaultLink.id)
    ).all()
    current = [(link.dst_ref, link.dst_title) for link in existing]
    if current == desired:
        return
    for link in existing:
        session.delete(link)
    for dst_ref, dst_title in desired:
        session.add(
            VaultLink(src_ref=source_ref, dst_ref=dst_ref, dst_title=dst_title)
        )


def _remove_vault_source(session: Session, source_ref: str) -> int:
    from adaptive_academy.engine.memory import remove_source

    removed = remove_source(session, source_ref)
    for link in session.exec(
        select(VaultLink).where(VaultLink.src_ref == source_ref)
    ).all():
        session.delete(link)
    return removed


def reindex_vault(
    session: Session,
    topic_id: int,
    vault_path: str,
    *,
    subfolder: str = "",
    only_refs: set[str] | None = None,
    progress: dict[str, int] | None = None,
    retriever: Retriever | None = None,
    deadline: float | None = None,
) -> IndexResult:
    """Index vault note text and wikilinks with one transaction per file.

    With ``only_refs`` (file URIs), only those notes are (re)indexed and only their
    orphans removed — used by all-topic sweeps so one topic never claims another's notes.
    """
    from adaptive_academy.engine.memory import (
        IndexResult,
        bump_progress,
        concept_name_index,
        content_hash,
        index_text,
        make_context,
        split_markdown,
        tag_chunk_concepts,
    )

    vault = safe_vault_dir(vault_path)
    root = safe_child(vault, subfolder) if subfolder else vault
    paths, rejected_paths, complete = _scan_notes_with_skips(root, vault=vault, deadline=deadline)
    if only_refs is not None:
        paths = [path for path in paths if path.resolve().as_uri() in only_refs]
        rejected_paths = []
    current_refs = {path.resolve().as_uri() for path in paths}
    # A capped or deadline-stopped scan is partial work: report it as truncated.
    truncated = (not complete) or (deadline is not None and time.perf_counter() >= deadline)
    title_index: dict[str, str] = {}
    titles_complete = False
    if not truncated:
        title_index, titles_complete = build_title_index_checked(vault, deadline=deadline)
    if not titles_complete:
        truncated = True  # link resolution would be partial; treat the run as truncated
    truncated = truncated or (
        deadline is not None and time.perf_counter() >= deadline
    )
    indexed = 0
    skipped = len(rejected_paths)
    removed = 0
    bump_progress(progress, skipped=len(rejected_paths))
    progress_seen = {"indexed": 0, "skipped": skipped, "removed": 0}
    concept_names = concept_name_index(session, topic_id)

    for path in rejected_paths:
        session.add(
            AgentEvent(
                topic_id=topic_id,
                kind="memory:reindex_skipped",
                detail=f"{path.absolute().as_uri()} outside-vault-or-symlink",
            )
        )
    if rejected_paths:
        session.commit()

    for path in paths:
        if deadline is not None and time.perf_counter() >= deadline:
            truncated = True
            break
        source_ref = path.resolve().as_uri()
        existing = session.exec(
            select(Chunk)
            .where(
                Chunk.kind == "vault_note",
                Chunk.source_ref == source_ref,
            )
            .order_by(Chunk.ordinal)
        ).all()
        if only_refs is None and any(
            chunk.topic_id is not None and chunk.topic_id != topic_id
            for chunk in existing
        ):
            skipped += 1
            session.add(
                AgentEvent(
                    topic_id=topic_id,
                    kind="memory:reindex_owned_elsewhere",
                    detail=source_ref,
                )
            )
            session.commit()
            bump_progress(progress, skipped=1)
            progress_seen["skipped"] += 1
            continue
        try:
            text, source_mtime = _read_index_text_with_mtime(path, vault=vault)
        except OSError:
            skipped += 1
            session.add(AgentEvent(
                topic_id=topic_id,
                kind="memory:reindex_skipped",
                detail=f"{source_ref} outside-vault-or-symlink",
            ))
            session.commit()
            bump_progress(progress, skipped=1)
            progress_seen["skipped"] += 1
            continue
        except UnicodeError as exc:
            skipped += 1
            session.add(AgentEvent(
                topic_id=topic_id, kind="memory:reindex_skipped",
                detail=f"{source_ref} {type(exc).__name__}"))
            session.commit()
            bump_progress(progress, skipped=1)
            progress_seen["skipped"] += 1
            continue

        frontmatter, _ = parse_frontmatter(text)
        title = note_title(text, path.stem)
        metadata = {
            "tags": _frontmatter_list(frontmatter.get("tags")),
            "aliases": _frontmatter_list(frontmatter.get("aliases")),
        }
        pieces = split_markdown(text)
        unchanged = len(existing) == len(pieces) and all(
            chunk.kind == "vault_note"
            and chunk.topic_id == topic_id
            and chunk.source_mtime == source_mtime
            and chunk.content_hash == content_hash(piece.text)
            and chunk.heading == piece.heading
            and chunk.context == make_context(title, piece.heading)
            and chunk.meta == metadata
            for chunk, piece in zip(existing, pieces, strict=True)
        )
        if unchanged:
            skipped += len(pieces)
            # Concepts/aliases may have appeared since the chunks were written; keep the
            # ChunkConcept links current even when no text changed.
            for chunk in existing:
                tag_chunk_concepts(session, chunk, concept_names)
        else:
            result = index_text(
                session,
                kind="vault_note",
                text=text,
                source_ref=source_ref,
                doc_title=title,
                topic_id=topic_id,
                meta=metadata,
                source_mtime=source_mtime,
                splitter=split_markdown,
                retriever=retriever,
            )
            indexed += result.indexed
            skipped += result.skipped
            removed += result.removed
        if titles_complete:
            _sync_vault_links(session, source_ref, text, title_index)
        session.commit()
        bump_progress(
            progress,
            indexed=indexed - progress_seen["indexed"],
            skipped=skipped - progress_seen["skipped"],
            removed=removed - progress_seen["removed"],
        )
        progress_seen = {"indexed": indexed, "skipped": skipped, "removed": removed}

    if complete and not truncated:
        root_prefix = root.resolve().as_uri().rstrip("/") + "/"
        existing_refs = {
            chunk.source_ref
            for chunk in session.exec(
                select(Chunk).where(
                    Chunk.kind == "vault_note",
                    Chunk.topic_id == topic_id,
                )
            ).all()
            if chunk.source_ref.startswith(root_prefix)
        }
        if only_refs is not None:
            existing_refs &= only_refs
        for source_ref in sorted(existing_refs - current_refs):
            if deadline is not None and time.perf_counter() >= deadline:
                truncated = True
                session.add(AgentEvent(
                    topic_id=topic_id, kind="memory:reindex_partial",
                    detail="deadline reached during orphan sweep; remaining orphans kept"))
                session.commit()
                break
            gone = _remove_vault_source(session, source_ref)
            removed += gone
            session.commit()
            bump_progress(progress, removed=gone)
    else:
        count = _MAX_SCAN_FILES if not complete else len(paths)
        session.add(
            AgentEvent(
                topic_id=topic_id,
                kind="memory:reindex_partial",
                detail=f"scan capped at {count} files; orphan sweep skipped",
            )
        )
        session.commit()

    session.add(
        AgentEvent(
            topic_id=topic_id,
            kind="memory:reindex",
            detail=f"indexed={indexed} skipped={skipped} removed={removed}",
        )
    )
    session.commit()
    return IndexResult(
        indexed=indexed,
        skipped=skipped,
        removed=removed,
        truncated=truncated,
    )


def _track_markdown(session: Session, track: Track) -> str:
    """Build a TrackView from the DB and render it (mirrors the curriculum.md route)."""
    phases = session.exec(
        select(Phase).where(Phase.track_id == track.id).order_by(Phase.position)
    ).all()
    pvs = []
    for p in phases:
        items = session.exec(
            select(Item).where(Item.phase_id == p.id).order_by(Item.position)
        ).all()
        d = session.exec(select(Deliverable).where(Deliverable.phase_id == p.id)).first()
        pvs.append(PhaseView(
            title=p.title, est_hours=p.est_hours, flags=p.flags,
            items=[ItemView(text=i.text, type=i.type, status=i.status) for i in items],
            deliverable=DeliverableView(
                text=d.text, kind=d.kind, acceptance_criteria=d.acceptance_criteria) if d else None,
        ))
    sidebars = session.exec(
        select(Sidebar).where(Sidebar.track_id == track.id).order_by(Sidebar.position)
    ).all()
    view = TrackView(
        title=track.title, overview=track.overview, phases=pvs,
        sidebars=[SidebarView(kind=s.kind, title=s.title, body=s.body) for s in sidebars])
    return track_to_markdown(view)


def _concept_verdict_summary(session: Session, concept: Concept) -> tuple[str, str]:
    """v1: verdict = the concept's knowledge level, but anti-Goodhart — a concept with NO
    assessments reads 'untested', never the default-'high' KnowledgeEstimate, and one whose
    assessments include no graded kind (assess.GRADING_KINDS: e.g. only shipped or taught)
    reads 'ungraded', since its estimate is still the curriculum's prior. summary = latest
    assessment. Full 5-signal triangulation lives in frontend competence.ts (porting is a follow-up)."""
    latest = session.exec(
        select(Assessment).where(Assessment.concept_id == concept.id)
        .order_by(Assessment.id.desc())).first()
    if latest is None:
        return "untested", "No assessments yet."
    if not graded_concept_ids(session, [concept.id]):
        verdict = "ungraded"
    else:
        est = session.exec(
            select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept.id)).first()
        if est is not None:
            verdict = est.level
        else:
            graded = session.exec(
                select(Assessment).where(Assessment.concept_id == concept.id,
                                         col(Assessment.kind).in_(GRADING_KINDS))
                .order_by(Assessment.id.desc())).first()
            verdict = level_from_score(graded.score)[0]
    bits = [f"Latest: **{latest.kind}**, score {latest.score:.2f}"]
    if latest.verdict:
        bits.append(latest.verdict)
    if latest.gaps:
        bits.append("Gaps: " + "; ".join(latest.gaps))
    return verdict, "  \n".join(bits)


def ingest_vault(
    session: Session,
    topic_id: int,
    vault_path: str,
    *,
    subfolder: str = "",
    retriever: Retriever | None = None,
) -> IngestResult:
    """Scan a vault for markdown notes and register them as `proposed` SourceDocs for the topic.
    Already-ingested notes (same file URL) are skipped, so re-running is safe."""
    vault = safe_vault_dir(vault_path)
    root = safe_child(vault, subfolder) if subfolder else vault
    existing = {
        s.url for s in session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic_id)).all()
    }
    titles: list[str] = []
    paths, _, _ = _scan_notes_with_skips(root, vault=vault)
    for path in paths:
        url = path.resolve().as_uri()
        if url in existing:
            continue
        try:
            text = _read_text(
                path,
                vault=vault,
                limit=_MAX_READ_CHARS,
                errors="replace",
            )
        except OSError:
            continue
        title = note_title(text, path.stem)
        session.add(SourceDoc(
            topic_id=topic_id, title=title, url=url, tier=2, summary=note_summary(text),
            angle="vault", added_by="obsidian", status="proposed"))
        existing.add(url)
        titles.append(title)
    if titles:
        session.add(AgentEvent(
            topic_id=topic_id, kind="vault:ingest", detail=f"{len(titles)} note(s) from vault"))
    session.commit()
    reindex_vault(
        session,
        topic_id,
        vault_path,
        subfolder=subfolder,
        retriever=retriever,
    )
    return IngestResult(count=len(titles), titles=titles)


def export_vault(session: Session, topic_id: int, vault_path: str) -> ExportResult:
    """Write the topic's hub note + per-concept notes into `<vault>/Adaptive Academy/<topic>/`.
    Idempotent. The hub note is regenerated. A concept note is created with its header and
    notebook section, or, when it exists, only its notebook section (and its frontmatter
    `verdict:` value) is rewritten (engine/notebook_sync.py): what the learner wrote outside
    the markers stays as it is. Folder and file names never take over another topic's or
    concept's note: names that slug alike get an id suffix."""
    from adaptive_academy.engine.notebook import MarkerError
    from adaptive_academy.engine.notebook_sync import (
        NOTEBOOK_SYNC,
        UnsafeNote,
        concept_note_path,
        planned_concept_stems,
        problem_text,
        topic_folder,
        write_concept_note,
        write_hub_note,
    )

    vault = safe_vault_dir(vault_path)
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise ValueError("topic not found")
    folder, hub_stem = topic_folder(session, vault, topic)

    track = session.exec(select(Track).where(Track.topic_id == topic_id)).first()
    overview = track.overview if track else ""
    track_md = _track_markdown(session, track) if track else ""
    concepts = (
        session.exec(select(Concept).where(Concept.track_id == track.id)
                     .order_by(Concept.id)).all() if track else []
    )

    # Where each concept's note goes, before the hub links to them.
    planned = planned_concept_stems(concepts)
    concepts_dir = safe_child(folder, "Concepts")
    concepts_dir.mkdir(parents=True, exist_ok=True)
    paths: dict[int, Path] = {}
    problems: list[str] = []
    for c in concepts:
        try:
            paths[c.id] = concept_note_path(vault, concepts_dir, c, planned[c.id], concepts)
        except UnsafeNote as exc:
            message = f"{planned[c.id]}.md: {problem_text(exc)}"
            problems.append(message)
            NOTEBOOK_SYNC.record_problem(c.id, f"Couldn't update {message}")

    written: list[str] = []
    hub_path = write_hub_note(
        vault, folder, hub_stem,
        render_hub_note(topic.title, overview, track_md, [c.name for c in concepts],
                        concept_stems=[paths[c.id].stem if c.id in paths else planned[c.id]
                                       for c in concepts],
                        topic_id=topic.id),
        replace=True)
    written.append(str(hub_path))

    for c in concepts:
        if c.id not in paths:
            continue
        try:
            note_path = write_concept_note(session, vault, topic, c, path=paths[c.id],
                                           hub_stem=hub_stem)
        except (MarkerError, UnsafeNote) as exc:
            message = f"{paths[c.id].name}: {problem_text(exc)}"
            problems.append(message)
            NOTEBOOK_SYNC.record_problem(c.id, f"Couldn't update {message}")
            continue
        NOTEBOOK_SYNC.note_ok(c.id)
        written.append(str(note_path))

    detail = f"{len(written)} note(s) to vault"
    if problems:
        detail += f", {len(problems)} left unchanged"
    session.add(AgentEvent(topic_id=topic_id, kind="vault:export", detail=detail))
    session.commit()
    return ExportResult(written=written, problems=problems)


def export_all_topics(session: Session, vault_path: str) -> ExportAllResult:
    """Mirror every one of the learner's topics into its own `Adaptive Academy/<topic>/`
    folder in one pass. The demo topic is sample data, not the learner's, so it is skipped
    (an explicit single-topic export of it via export_vault still works: that is a choice)."""
    from adaptive_academy.engine.notebook_sync import NOTEBOOK_SYNC, UnsafeNote

    safe_vault_dir(vault_path)  # validate once, up front
    topics = session.exec(select(Topic).where(col(Topic.is_demo).is_(False))).all()
    written: list[str] = []
    problems: list[str] = []
    for t in topics:
        try:
            res = export_vault(session, t.id, vault_path)
        except UnsafeNote as exc:
            # This topic's folder or hub can't be written safely: say so, do the rest.
            session.rollback()
            problems.append(f"{t.title}: {exc}")
            continue
        written.extend(res.written)
        problems.extend(res.problems)

    NOTEBOOK_SYNC.clear_problem("queue")  # every topic's notes were just rewritten
    return ExportAllResult(topics=len(topics), written=written, problems=problems)
