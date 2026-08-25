"""Obsidian vault integration — pure core (slugs, frontmatter, scanning, path-safety, renderers).

A vault is a folder of markdown on disk; everything here is local file I/O or pure string work,
honoring local-first (no external services, no data egress). Orchestration that touches the DB
lives in the API layer; this module stays side-effect-light and unit-testable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from sqlmodel import Session, select

from adaptive_academy.engine.assess import level_from_score
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

# We own this subfolder for exports; ingest skips it to avoid a feedback loop.
EXPORT_FOLDER = "Adaptive Academy"
_SUMMARY_CAP = 280
_MAX_SCAN_FILES = 2000
_MAX_READ_CHARS = 100_000  # only the head is needed for title/summary


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (name or "").lower())
    return s.strip("-")


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

def scan_notes(root: Path, *, skip_dirs: frozenset[str] = frozenset({EXPORT_FOLDER})) -> list[Path]:
    """Recursively list `*.md` under root, skipping our export folder and dotfolders."""
    out: list[Path] = []
    for p in sorted(root.rglob("*.md")):
        rel_parts = p.relative_to(root).parts
        if any(part in skip_dirs or part.startswith(".") for part in rel_parts[:-1]):
            continue
        out.append(p)
        if len(out) >= _MAX_SCAN_FILES:
            break
    return out


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


def _read_index_text(path: Path) -> str:
    from adaptive_academy.engine.memory import MAX_INDEX_CHARS

    with path.open(encoding="utf-8", errors="strict") as handle:
        return handle.read(MAX_INDEX_CHARS)


def build_title_index(root: Path | str) -> dict[str, str]:
    """Build a case-folded title and frontmatter-alias map for one vault sweep."""
    resolved_root = Path(root).resolve()
    titles: dict[str, str] = {}
    for path in scan_notes(resolved_root):
        try:
            text = _read_index_text(path)
        except (OSError, UnicodeError):
            continue
        frontmatter, _ = parse_frontmatter(text)
        names = [note_title(text, path.stem), *_frontmatter_list(frontmatter.get("aliases"))]
        for name in names:
            key = name.strip().casefold()
            if key:
                titles.setdefault(key, path.resolve().as_uri())
    return titles


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
    topic_title: str, overview: str, track_markdown: str, concept_names: list[str]
) -> str:
    fm = render_frontmatter({"title": topic_title, "tags": ["adaptive-academy"]})
    parts = [fm, f"# {topic_title}\n"]
    if overview:
        parts.append(overview + "\n")
    if concept_names:
        parts.append("## Concepts\n")
        parts.append(
            "\n".join(f"- [[{slugify(n)}|{n}]]" for n in concept_names) + "\n"
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


@dataclass
class ExportAllResult:
    topics: int
    written: list[str] = field(default_factory=list)


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
) -> IndexResult:
    """Index vault note text and wikilinks with one transaction per file."""
    from adaptive_academy.engine.memory import (
        IndexResult,
        content_hash,
        index_text,
        make_context,
        split_markdown,
    )

    vault = safe_vault_dir(vault_path)
    root = safe_child(vault, subfolder) if subfolder else vault
    paths = scan_notes(root)
    current_refs = {path.resolve().as_uri() for path in paths}
    title_index = build_title_index(vault)
    indexed = 0
    skipped = 0
    removed = 0

    for path in paths:
        source_ref = path.resolve().as_uri()
        try:
            text = _read_index_text(path)
            source_mtime = path.stat().st_mtime
        except (OSError, UnicodeError) as exc:
            skipped += 1
            session.add(AgentEvent(
                topic_id=topic_id, kind="memory:reindex_skipped",
                detail=f"{source_ref} {type(exc).__name__}"))
            session.commit()
            continue

        frontmatter, _ = parse_frontmatter(text)
        title = note_title(text, path.stem)
        metadata = {
            "tags": _frontmatter_list(frontmatter.get("tags")),
            "aliases": _frontmatter_list(frontmatter.get("aliases")),
        }
        pieces = split_markdown(text)
        existing = session.exec(
            select(Chunk)
            .where(Chunk.source_ref == source_ref)
            .order_by(Chunk.ordinal)
        ).all()
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
            )
            indexed += result.indexed
            skipped += result.skipped
            removed += result.removed
        _sync_vault_links(session, source_ref, text, title_index)
        session.commit()

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
    for source_ref in sorted(existing_refs - current_refs):
        removed += _remove_vault_source(session, source_ref)
        session.commit()

    session.add(
        AgentEvent(
            topic_id=topic_id,
            kind="memory:reindex",
            detail=f"indexed={indexed} skipped={skipped} removed={removed}",
        )
    )
    session.commit()
    return IndexResult(indexed=indexed, skipped=skipped, removed=removed)


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
    assessments reads 'untested', never the default-'high' KnowledgeEstimate. summary = latest
    assessment. Full 5-signal triangulation lives in frontend competence.ts (porting is a follow-up)."""
    latest = session.exec(
        select(Assessment).where(Assessment.concept_id == concept.id)
        .order_by(Assessment.id.desc())).first()
    if latest is None:
        return "untested", "No assessments yet."
    est = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept.id)).first()
    verdict = est.level if est else level_from_score(latest.score)[0]
    bits = [f"Latest: **{latest.kind}** — score {latest.score:.2f}"]
    if latest.verdict:
        bits.append(latest.verdict)
    if latest.gaps:
        bits.append("Gaps: " + "; ".join(latest.gaps))
    return verdict, "  \n".join(bits)


def ingest_vault(
    session: Session, topic_id: int, vault_path: str, *, subfolder: str = ""
) -> IngestResult:
    """Scan a vault for markdown notes and register them as `proposed` SourceDocs for the topic.
    Already-ingested notes (same file URL) are skipped, so re-running is safe."""
    vault = safe_vault_dir(vault_path)
    root = safe_child(vault, subfolder) if subfolder else vault
    existing = {
        s.url for s in session.exec(select(SourceDoc).where(SourceDoc.topic_id == topic_id)).all()
    }
    titles: list[str] = []
    for path in scan_notes(root):
        url = path.resolve().as_uri()
        if url in existing:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")[:_MAX_READ_CHARS]
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
    reindex_vault(session, topic_id, vault_path, subfolder=subfolder)
    return IngestResult(count=len(titles), titles=titles)


def export_vault(session: Session, topic_id: int, vault_path: str) -> ExportResult:
    """Write the topic's hub note + per-concept notes into `<vault>/Adaptive Academy/<topic>/`.
    Idempotent — we own that folder and regenerate it; the learner's own notes are never touched."""
    vault = safe_vault_dir(vault_path)
    topic = session.get(Topic, topic_id)
    if topic is None:
        raise ValueError("topic not found")
    topic_slug = slugify(topic.title)
    base = safe_child(vault, EXPORT_FOLDER, topic_slug)
    base.mkdir(parents=True, exist_ok=True)

    track = session.exec(select(Track).where(Track.topic_id == topic_id)).first()
    overview = track.overview if track else ""
    track_md = _track_markdown(session, track) if track else ""
    concepts = (
        session.exec(select(Concept).where(Concept.track_id == track.id)).all() if track else []
    )

    written: list[str] = []
    hub_path = safe_child(base, f"{topic_slug}.md")
    hub_path.write_text(
        render_hub_note(topic.title, overview, track_md, [c.name for c in concepts]),
        encoding="utf-8")
    written.append(str(hub_path))

    if concepts:
        concepts_dir = safe_child(base, "Concepts")
        concepts_dir.mkdir(parents=True, exist_ok=True)
        for c in concepts:
            verdict, summary = _concept_verdict_summary(session, c)
            note_path = safe_child(concepts_dir, f"{slugify(c.name)}.md")
            note_path.write_text(
                render_concept_note(c.name, verdict, c.is_load_bearing, summary, topic_slug),
                encoding="utf-8")
            written.append(str(note_path))

    session.add(AgentEvent(
        topic_id=topic_id, kind="vault:export", detail=f"{len(written)} note(s) to vault"))
    session.commit()
    return ExportResult(written=written)


def export_all_topics(session: Session, vault_path: str) -> ExportAllResult:
    """Mirror every topic into its own `Adaptive Academy/<topic>/` folder in one pass."""
    safe_vault_dir(vault_path)  # validate once, up front
    topics = session.exec(select(Topic)).all()
    written: list[str] = []
    for t in topics:
        written.extend(export_vault(session, t.id, vault_path).written)
    return ExportAllResult(topics=len(topics), written=written)
