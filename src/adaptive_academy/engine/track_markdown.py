# src/adaptive_academy/engine/track_markdown.py
import re
from dataclasses import dataclass, field

_STATUS_TO_BOX = {"todo": " ", "doing": "-", "done": "x"}
_BOX_TO_STATUS = {v: k for k, v in _STATUS_TO_BOX.items()}


@dataclass
class ItemView:
    text: str
    type: str = "read"
    status: str = "todo"
    concept_refs: list[str] = field(default_factory=list)  # DB-only; not serialized


@dataclass
class DeliverableView:
    text: str
    kind: str = "blog"
    acceptance_criteria: list[str] = field(default_factory=list)


@dataclass
class SidebarView:
    kind: str
    title: str
    body: str = ""


@dataclass
class PhaseView:
    title: str
    est_hours: str = ""
    flags: list[str] = field(default_factory=list)
    items: list[ItemView] = field(default_factory=list)
    deliverable: "DeliverableView | None" = None


@dataclass
class TrackView:
    title: str
    overview: str = ""
    phases: list[PhaseView] = field(default_factory=list)
    sidebars: list[SidebarView] = field(default_factory=list)


def track_to_markdown(track: TrackView) -> str:
    """Serialize a TrackView to canonical markdown (the round-trip source of truth)."""
    lines: list[str] = [f"# {track.title}", ""]
    if track.overview:
        lines += [track.overview, ""]

    for i, p in enumerate(track.phases):
        header = f"## Phase {i + 1} — {p.title}"
        if p.est_hours:
            header += f" ({p.est_hours})"
        for fl in p.flags:
            header += f" · _{fl}_"
        lines.append(header)
        for it in p.items:
            box = _STATUS_TO_BOX.get(it.status, " ")
            lines.append(f"- [{box}] ({it.type}) {it.text}")
        if p.deliverable:
            d = p.deliverable
            lines.append(f"- **🎯 Ship:** ({d.kind}) {d.text}")
            for c in d.acceptance_criteria:
                lines.append(f"  - acceptance: {c}")
        lines.append("")

    for s in track.sidebars:
        lines.append(f"## Sidebar: {s.title}")
        lines.append(f"_kind: {s.kind}_")
        lines.append("")
        if s.body:
            lines += [s.body, ""]

    return "\n".join(lines).rstrip() + "\n"


_PHASE_RE = re.compile(r"^Phase \d+ — (?P<rest>.*)$")
_FLAG_RE = re.compile(r" · _(\w+)_")
_EST_RE = re.compile(r" \(([^)]*)\)$")
_ITEM_RE = re.compile(r"^- \[(?P<box>.)\] \((?P<type>\w+)\) (?P<text>.*)$")
_SHIP_RE = re.compile(r"^- \*\*🎯 Ship:\*\* \((?P<kind>\w+)\) (?P<text>.*)$")
_ACCEPT_PREFIX = "  - acceptance: "
_SIDEBAR_PREFIX = "## Sidebar: "
_KIND_RE = re.compile(r"^_kind: (?P<kind>\w+)_$")


def _parse_phase_header(rest: str) -> tuple[str, str, list[str]]:
    flags = _FLAG_RE.findall(rest)
    rest = _FLAG_RE.sub("", rest)
    est = ""
    m = _EST_RE.search(rest)
    if m:
        est = m.group(1)
        rest = rest[: m.start()]
    return rest.strip(), est, flags


def markdown_to_track(md: str) -> TrackView:
    """Parse markdown produced by track_to_markdown back into a TrackView."""
    lines = md.splitlines()
    title = ""
    overview_lines: list[str] = []
    phases: list[PhaseView] = []
    sidebars: list[SidebarView] = []

    i, n = 0, len(lines)
    # Title.
    while i < n and not lines[i].startswith("# "):
        i += 1
    if i < n:
        title = lines[i][2:].strip()
        i += 1
    # Overview: everything up to the first "## ".
    while i < n and not lines[i].startswith("## "):
        if lines[i].strip():
            overview_lines.append(lines[i])
        i += 1

    cur_phase: PhaseView | None = None
    cur_sidebar: SidebarView | None = None
    sidebar_body: list[str] = []

    def flush_sidebar() -> None:
        nonlocal cur_sidebar, sidebar_body
        if cur_sidebar is not None:
            cur_sidebar.body = "\n".join(sidebar_body).strip()
            sidebars.append(cur_sidebar)
        cur_sidebar, sidebar_body = None, []

    while i < n:
        line = lines[i]
        if line.startswith(_SIDEBAR_PREFIX):
            flush_sidebar()
            cur_phase = None
            cur_sidebar = SidebarView(kind="", title=line[len(_SIDEBAR_PREFIX):].strip())
            i += 1
            if i < n and (m := _KIND_RE.match(lines[i].strip())):
                cur_sidebar.kind = m.group("kind")
                i += 1
            continue
        if line.startswith("## "):
            flush_sidebar()
            m = _PHASE_RE.match(line[3:])
            ptitle, est, flags = _parse_phase_header(m.group("rest")) if m else (line[3:].strip(), "", [])
            cur_phase = PhaseView(title=ptitle, est_hours=est, flags=flags)
            phases.append(cur_phase)
            i += 1
            continue
        if cur_sidebar is not None:
            sidebar_body.append(line)
            i += 1
            continue
        if cur_phase is not None:
            if m := _ITEM_RE.match(line):
                cur_phase.items.append(ItemView(
                    text=m.group("text"), type=m.group("type"),
                    status=_BOX_TO_STATUS.get(m.group("box"), "todo")))
            elif m := _SHIP_RE.match(line):
                cur_phase.deliverable = DeliverableView(
                    text=m.group("text"), kind=m.group("kind"))
            elif line.startswith(_ACCEPT_PREFIX) and cur_phase.deliverable is not None:
                cur_phase.deliverable.acceptance_criteria.append(line[len(_ACCEPT_PREFIX):])
        i += 1

    flush_sidebar()
    return TrackView(title=title, overview="\n".join(overview_lines).strip(),
                     phases=phases, sidebars=sidebars)
