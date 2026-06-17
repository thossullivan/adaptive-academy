"""Obsidian vault integration — pure core (slugs, frontmatter, scanning, path-safety, renderers).

A vault is a folder of markdown on disk; everything here is local file I/O or pure string work,
honoring local-first (no external services, no data egress). Orchestration that touches the DB
lives in the API layer; this module stays side-effect-light and unit-testable.
"""

import re
from pathlib import Path

# We own this subfolder for exports; ingest skips it to avoid a feedback loop.
EXPORT_FOLDER = "Adaptive Academy"
_SUMMARY_CAP = 280
_MAX_SCAN_FILES = 2000


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
