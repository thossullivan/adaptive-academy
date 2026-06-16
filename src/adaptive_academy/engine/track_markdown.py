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
        # est_hours uses a "· ⏳ " marker (not bare parens) so a phase title may itself
        # end in "(...)" without the parser mistaking it for est_hours.
        header = f"## Phase {i + 1} — {p.title}"
        if p.est_hours:
            header += f" · ⏳ {p.est_hours}"
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
_EST_RE = re.compile(r" · ⏳ (.*)$")
_ITEM_RE = re.compile(r"^- \[(?P<box>.)\] \((?P<type>\w+)\) (?P<text>.*)$")
_SHIP_RE = re.compile(r"^- \*\*🎯 Ship:\*\* \((?P<kind>\w+)\) (?P<text>.*)$")
_ACCEPT_PREFIX = "  - acceptance: "
_SIDEBAR_PREFIX = "## Sidebar: "
_KIND_RE = re.compile(r"^_kind: (?P<kind>\w+)_$")

# Import leniency: accept untyped checkbox items ("- [ ] text") and infer a type.
_ITEM_UNTYPED_RE = re.compile(r"^- \[(?P<box>.)\] (?P<text>.*)$")
_TYPE_KEYWORDS: list[tuple[str, tuple[str, ...]]] = [
    ("watch", ("3blue1brown", "video", "lecture", "youtube")),
    ("build", ("build", "train ", "implement", "coding", "curate", "replicat")),
    ("write", ("blog", "writeup", "write up", "write-up")),
]


def _infer_type(text: str) -> str:
    """Infer an item type from its text — import leniency for untyped checkbox items."""
    low = text.lower()
    for typ, kws in _TYPE_KEYWORDS:
        if any(k in low for k in kws):
            return typ
    return "read"


def _parse_phase_header(rest: str) -> tuple[str, str, list[str]]:
    flags = _FLAG_RE.findall(rest)
    rest = _FLAG_RE.sub("", rest)
    est = ""
    m = _EST_RE.search(rest)
    if m:
        est = m.group(1)
        rest = rest[: m.start()]
    return rest.strip(), est, flags


def _block_is_phase(body: list[str]) -> bool:
    """A "## " section is a phase if it holds at least one checkbox item or a Ship line."""
    return any(_ITEM_UNTYPED_RE.match(ln) or _SHIP_RE.match(ln) for ln in body)


def _parse_phase_block(heading: str, body: list[str]) -> PhaseView:
    """Build a PhaseView from a "## " heading + its body lines. Items may be canonical
    typed (`(type) text`) or untyped (type inferred)."""
    m = _PHASE_RE.match(heading)
    ptitle, est, flags = _parse_phase_header(m.group("rest")) if m else (heading.strip(), "", [])
    phase = PhaseView(title=ptitle, est_hours=est, flags=flags)
    for line in body:
        if mt := _ITEM_RE.match(line):
            phase.items.append(ItemView(text=mt.group("text"), type=mt.group("type"),
                                        status=_BOX_TO_STATUS.get(mt.group("box"), "todo")))
        elif mu := _ITEM_UNTYPED_RE.match(line):
            phase.items.append(ItemView(text=mu.group("text"), type=_infer_type(mu.group("text")),
                                        status=_BOX_TO_STATUS.get(mu.group("box"), "todo")))
        elif ms := _SHIP_RE.match(line):
            phase.deliverable = DeliverableView(text=ms.group("text"), kind=ms.group("kind"))
        elif line.startswith(_ACCEPT_PREFIX) and phase.deliverable is not None:
            phase.deliverable.acceptance_criteria.append(line[len(_ACCEPT_PREFIX):])
    return phase


def markdown_to_track(md: str) -> TrackView:
    """Parse markdown into a TrackView.

    Accepts the canonical export AND lenient real-world trackers: untyped checkbox items
    (type inferred) and prose "## " sections (kept as reference sidebars). A
    "## Sidebar:" block keeps the legacy behaviour — its body may contain "## "/"- [ ]"
    lines and runs until the next "## Sidebar:". See
    docs/superpowers/specs/2026-06-16-import-robustness.md.
    """
    lines = md.splitlines()
    n = len(lines)
    i = 0
    # Title.
    title = ""
    while i < n and not lines[i].startswith("# "):
        i += 1
    if i < n:
        title = lines[i][2:].strip()
        i += 1
    # Overview: everything up to the first "## " (keep internal blanks; strip the ends).
    overview_lines: list[str] = []
    while i < n and not lines[i].startswith("## "):
        overview_lines.append(lines[i])
        i += 1

    phases: list[PhaseView] = []
    sidebars: list[SidebarView] = []
    while i < n:
        line = lines[i]
        if line.startswith(_SIDEBAR_PREFIX):
            # Canonical sidebar: body runs until the NEXT "## Sidebar:" (may contain "## ").
            sb_title = line[len(_SIDEBAR_PREFIX):].strip()
            i += 1
            kind = ""
            if i < n and (km := _KIND_RE.match(lines[i].strip())):
                kind = km.group("kind")
                i += 1
            body: list[str] = []
            while i < n and not lines[i].startswith(_SIDEBAR_PREFIX):
                body.append(lines[i])
                i += 1
            sidebars.append(SidebarView(kind=kind, title=sb_title, body="\n".join(body).strip()))
        elif line.startswith("## "):
            # A section: collect its body up to the next "## ", then classify.
            heading = line[3:]
            i += 1
            body = []
            while i < n and not lines[i].startswith("## "):
                body.append(lines[i])
                i += 1
            if _PHASE_RE.match(heading) or _block_is_phase(body):
                phases.append(_parse_phase_block(heading, body))
            else:
                sidebars.append(SidebarView(kind="reference", title=heading.strip(),
                                            body="\n".join(body).strip()))
        else:
            i += 1

    return TrackView(title=title, overview="\n".join(overview_lines).strip(),
                     phases=phases, sidebars=sidebars)
