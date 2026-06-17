"""Obsidian vault integration — pure core (slugs, frontmatter, scanning, path-safety, renderers).

A vault is a folder of markdown on disk; everything here is local file I/O or pure string work,
honoring local-first (no external services, no data egress). Orchestration that touches the DB
lives in the API layer; this module stays side-effect-light and unit-testable.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

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
    Concept,
    Deliverable,
    Item,
    KnowledgeEstimate,
    Phase,
    Sidebar,
    SourceDoc,
    Topic,
    Track,
)

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
