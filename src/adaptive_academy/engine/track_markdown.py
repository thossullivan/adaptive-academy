# src/adaptive_academy/engine/track_markdown.py
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
