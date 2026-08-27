"""Map Revision — learnings-aware re-research for a Program's milestone map.

This module owns: the deterministic learnings digest (this task), and (later
tasks) the 3-angle freshness pass, diff synthesis, and per-change apply logic.
Spec: docs/superpowers/specs/2026-07-10-map-revision.md
"""

from collections import Counter
from dataclasses import dataclass

from sqlmodel import Session, select

from adaptive_academy.engine import graph
from adaptive_academy.engine.aliases import group_level
from adaptive_academy.engine.fanout import fan_out_with_retry
from adaptive_academy.engine.gates import evaluate_concept, milestone_load_bearing
from adaptive_academy.llm.researcher_types import RawSource, ResearcherClient, SearchBrief
from adaptive_academy.llm.structured import structured_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    ConceptAlias,
    MapChange,
    MapRevision,
    Milestone,
    Program,
    ProgramIntent,
    ProgramTopicLink,
    Track,
)
from adaptive_academy.prompts import PROGRAM_REVISION
from adaptive_academy.engine.untrusted import escape_markers


def build_learnings_digest(session: Session, program: Program) -> str:
    """Deterministic, no-LLM summary of what the learner has proven so far.

    Feeds the revision synthesis prompt. Skips archived milestones. Uses the
    same evidence verdicts the gates use — the digest and the gate never
    disagree about what is verified.
    """
    lines = [f"PROGRAM: {program.title} — status {program.status}"]
    milestones = session.exec(
        select(Milestone)
        .where(Milestone.program_id == program.id, Milestone.archived == False)  # noqa: E712
        .order_by(Milestone.order_index)
    ).all()
    if not milestones:
        lines.append("no milestones yet")
        return "\n".join(lines)

    for i, m in enumerate(milestones, start=1):
        links = session.exec(
            select(ProgramTopicLink).where(ProgramTopicLink.milestone_id == m.id)
        ).all()
        counts = Counter(link.status for link in links)
        count_str = ", ".join(
            f"{counts[s]} {s}" for s in ("started", "stub", "proposed", "pruned") if counts[s]
        ) or "no topics"
        lines.append(f"LEG {i}: {m.title} [gate: {m.gate_status}] — topics: {count_str}")
        concepts = milestone_load_bearing(session, m)
        if concepts:
            verdicts = []
            for c in sorted(concepts, key=lambda c: c.name):
                rows = session.exec(
                    select(Assessment).where(Assessment.concept_id == c.id)
                ).all()
                verdicts.append(f"{c.name}={evaluate_concept(c.id, c.name, rows).verdict}")
            lines.append("  evidence: " + ", ".join(verdicts))

    aliases = session.exec(
        select(ConceptAlias).where(ConceptAlias.program_id == program.id)
    ).all()
    groups: dict[str, list[int]] = {}
    for a in aliases:
        groups.setdefault(a.canonical_name, []).append(a.concept_id)
    if groups:
        knowledge = []
        for name in sorted(groups):
            level = group_level(session, groups[name])
            if level:
                knowledge.append(f"{name}={level}")
        if knowledge:
            lines.append("KNOWLEDGE (alias groups): " + ", ".join(knowledge))
    return "\n".join(lines)


# (angle_key, query_template) — {goal}/{focus}/{since} are filled in.
REVISION_ANGLES: list[tuple[str, str]] = [
    ("whats_new", "Important developments in {focus} since {since} relevant to {goal}"),
    ("curricula_check", "Changes since {since} in canonical curricula, courses, or qualifying-exam syllabi for {goal}"),
    ("frontier_shifts", "New architecture families, methods, or results since {since} that would change a 1-2 year study plan for {focus}"),
]


def build_revision_briefs(goal: str, focus: str, since_label: str) -> list[SearchBrief]:
    return [SearchBrief(angle=a, query=t.format(goal=goal, focus=focus or goal, since=since_label))
            for a, t in REVISION_ANGLES]


REVISION_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "map_health": {"type": "string"},
        "changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": [
                        "add_topic", "add_milestone", "revise_milestone",
                        "prune_topic", "prune_milestone"]},
                    "payload": {"type": "object"},
                    "why": {"type": "string"},
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["kind", "payload", "why"],
            },
        },
    },
    "required": ["map_health", "changes"],
}


def serialize_map(session: Session, program: Program) -> str:
    """The current map, with database ids and statuses, for the synthesis prompt.
    Archived milestones are excluded — they are not revisable surface."""
    lines = [f"PROGRAM: {program.title}"]
    milestones = session.exec(
        select(Milestone)
        .where(Milestone.program_id == program.id, Milestone.archived == False)  # noqa: E712
        .order_by(Milestone.order_index)
    ).all()
    for m in milestones:
        lines.append(f"milestone id={m.id} [gate: {m.gate_status}]: {m.title} — {m.success_criteria}")
        for link in session.exec(
            select(ProgramTopicLink).where(ProgramTopicLink.milestone_id == m.id)
        ).all():
            lines.append(f"  link id={link.id} ({link.status}): {link.proposed_title}")
    return "\n".join(lines)


def _milestone_untouchable(session: Session, m: Milestone) -> bool:
    """Started work or a passed gate makes a milestone immune to revise/prune."""
    if m.gate_status == "passed":
        return True
    started = session.exec(
        select(ProgramTopicLink).where(
            ProgramTopicLink.milestone_id == m.id,
            ProgramTopicLink.status == "started",
        )
    ).first()
    return started is not None


def validate_change(session: Session, program: Program, kind: str, payload: dict) -> str | None:
    """Shared parse-time AND apply-time gate. Returns a reason to drop/refuse, or None."""

    def _milestone(mid) -> Milestone | None:
        m = session.get(Milestone, mid) if isinstance(mid, int) else None
        return m if m is not None and m.program_id == program.id and not m.archived else None

    if kind == "add_topic":
        m = _milestone(payload.get("milestone_id"))
        if m is None:
            return "unresolvable milestone"
        title = str(payload.get("title", "")).strip()
        if not title:
            return "missing title"
        existing = session.exec(
            select(ProgramTopicLink).where(ProgramTopicLink.milestone_id == m.id)
        ).all()
        if any(link.status != "pruned"
               and link.proposed_title.strip().casefold() == title.casefold()
               for link in existing):
            return "duplicate topic title"
        return None
    if kind == "add_milestone":
        after = payload.get("after_milestone_id")
        if after is not None and _milestone(after) is None:
            return "unresolvable after_milestone_id"
        if not str(payload.get("title", "")).strip():
            return "missing title"
        return None
    if kind == "revise_milestone":
        m = _milestone(payload.get("milestone_id"))
        if m is None:
            return "unresolvable milestone"
        if _milestone_untouchable(session, m):
            return "milestone is started or passed"
        if payload.get("title") is None and payload.get("success_criteria") is None:
            return "no fields to revise"
        return None
    if kind == "prune_milestone":
        m = _milestone(payload.get("milestone_id"))
        if m is None:
            return "unresolvable milestone"
        if _milestone_untouchable(session, m):
            return "milestone is started or passed"
        return None
    if kind == "prune_topic":
        link_id = payload.get("link_id")
        link = session.get(ProgramTopicLink, link_id) if isinstance(link_id, int) else None
        if link is None:
            return "unresolvable link"
        m = session.get(Milestone, link.milestone_id)
        if m is None or m.program_id != program.id:
            return "unresolvable link"
        if link.status == "started":
            return "link is started"
        if link.status == "pruned":
            return "already pruned"
        return None
    return f"unknown kind {kind!r}"


@dataclass
class RevisionResult:
    revision: MapRevision
    changes: list[MapChange]
    events: list[AgentEvent]


def _since_label(session: Session, program: Program) -> str:
    latest = session.exec(
        select(MapRevision).where(MapRevision.program_id == program.id)
        .order_by(MapRevision.id.desc())
    ).first()
    dt = latest.created_at if latest else program.created_at
    return dt.strftime("%B %Y")


def run_revision(
    session: Session,
    program: Program,
    intent: ProgramIntent | None,
    *,
    researcher: ResearcherClient,
    llm: LLMClient,
    max_workers: int = 3,
) -> RevisionResult:
    """Fan out the freshness angles, synthesize a diff, persist it as proposals."""
    open_change = session.exec(
        select(MapChange)
        .join(MapRevision)
        .where(MapRevision.program_id == program.id, MapChange.status == "proposed")
    ).first()
    if open_change is not None:
        raise ValueError("program has an open revision; resolve it first")

    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(program_id=program.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    focus = intent.focus_area if intent else ""
    briefs = build_revision_briefs(program.goal_statement or program.title,
                                   focus, _since_label(session, program))
    emit("program_revision:plan", f"{len(briefs)} briefs")

    per_brief, failures, recovered = fan_out_with_retry(briefs, researcher, max_workers)
    raw: list[RawSource] = []
    for i, brief in enumerate(briefs):
        for s in per_brief[i]:
            s.angle = brief.angle
        if i in failures:
            emit("program_revision:subagent_error", f"{brief.angle}: {failures[i]}")
        elif i in recovered:
            emit("program_revision:subagent_retry",
                 f"{brief.angle}: recovered {recovered[i]} sources")
        else:
            emit("program_revision:subagent", f"{brief.angle}: {len(per_brief[i])} sources")
        raw.extend(per_brief[i])

    if briefs and not raw:
        session.commit()  # persist the trace so the failure is observable
        raise ValueError("revision research produced no sources; retry when connectivity is restored")

    emit("prompt", PROGRAM_REVISION.tag)
    user_msg = "\n\n".join([
        "<<<CURRENT MAP>>>", escape_markers(serialize_map(session, program)),
        "<<<LEARNINGS DIGEST>>>", escape_markers(build_learnings_digest(session, program)),
        "<<<SOURCES>>>",
        "\n".join(f"- [{s.angle}] {s.title} ({s.url}) — {s.summary}".rstrip(" —") for s in raw),
    ])
    data = structured_json(llm, PROGRAM_REVISION,
                           [{"role": "user", "content": user_msg}],
                           schema=REVISION_SCHEMA, tool_name="emit_revision")

    revision = MapRevision(program_id=program.id, map_health=str(data.get("map_health", "")))
    session.add(revision)
    session.flush()  # id without committing

    changes: list[MapChange] = []
    dropped = 0
    for ch in data.get("changes", []) or []:
        kind = str(ch.get("kind", ""))
        payload = ch.get("payload") if isinstance(ch.get("payload"), dict) else {}
        reason = validate_change(session, program, kind, payload)
        if reason is not None:
            dropped += 1
            continue
        change = MapChange(revision_id=revision.id, kind=kind, payload=payload,
                           why=str(ch.get("why", "")),
                           source_urls=list(ch.get("source_urls", []) or []))
        session.add(change)
        changes.append(change)
    if dropped:
        emit("program_revision:changes_dropped", f"{dropped} invalid change(s) discarded")
    emit("program_revision:done", f"{len(changes)} changes proposed")
    session.commit()
    session.refresh(revision)
    for c in changes:
        session.refresh(c)
    return RevisionResult(revision=revision, changes=changes, events=events)


def apply_change(session: Session, program: Program, change: MapChange) -> None:
    """Apply an accepted change atomically. Re-validates against CURRENT state —
    the map may have moved between the revision pass and this accept."""
    if change.status != "proposed":
        raise ValueError(f"change already {change.status}")
    reason = validate_change(session, program, change.kind, change.payload)
    if reason is not None:
        raise ValueError(f"change no longer applies: {reason}")

    payload = change.payload
    if change.kind == "add_topic":
        session.add(ProgramTopicLink(
            milestone_id=payload["milestone_id"], status="stub",
            proposed_title=str(payload["title"]).strip(),
            why=change.why, sources=change.source_urls, added_by="revision"))
    elif change.kind == "add_milestone":
        after = payload.get("after_milestone_id")
        siblings = session.exec(
            select(Milestone).where(Milestone.program_id == program.id)
            .order_by(Milestone.order_index)
        ).all()
        new_index = 0
        if after is not None:
            after_m = session.get(Milestone, after)
            new_index = after_m.order_index + 1
        for s in siblings:
            if s.order_index >= new_index:
                s.order_index += 1
                session.add(s)
        m = Milestone(program_id=program.id, title=str(payload["title"]).strip(),
                      success_criteria=str(payload.get("success_criteria", "")),
                      order_index=new_index,
                      depends_on=[after] if after is not None else [])
        session.add(m)
        session.flush()
        for t in payload.get("topics", []) or []:
            if t.get("title"):
                session.add(ProgramTopicLink(
                    milestone_id=m.id, status="stub", proposed_title=str(t["title"]),
                    why=str(t.get("why", "")), added_by="revision"))
    elif change.kind == "revise_milestone":
        m = session.get(Milestone, payload["milestone_id"])
        if payload.get("title") is not None:
            m.title = str(payload["title"])
        if payload.get("success_criteria") is not None:
            m.success_criteria = str(payload["success_criteria"])
        session.add(m)
    elif change.kind == "prune_topic":
        link = session.get(ProgramTopicLink, payload["link_id"])
        concepts = session.exec(select(Concept).join(Track).where(Track.topic_id == link.topic_id)).all()
        invalidated = graph.invalidate_concept_edges(
            session, (concept.id for concept in concepts if concept.id is not None))
        session.add(AgentEvent(program_id=program.id, kind="graph:invalidate",
                               detail=f"{invalidated} edges, mapchange:{change.id}"))
        link.status = "pruned"
        session.add(link)
    elif change.kind == "prune_milestone":
        m = session.get(Milestone, payload["milestone_id"])
        m.archived = True
        session.add(m)

    change.status = "accepted"
    session.add(change)
    session.commit()
    session.refresh(change)


def reject_change(session: Session, change: MapChange) -> None:
    if change.status != "proposed":
        raise ValueError(f"change already {change.status}")
    change.status = "rejected"
    session.add(change)
    session.commit()
    session.refresh(change)


def revision_suggested(session: Session, program: Program) -> bool:
    """True when a gate has passed since the map was last revised (spec §4.4)."""
    latest_pass = session.exec(
        select(AgentEvent).where(
            AgentEvent.program_id == program.id,
            AgentEvent.kind == "program:gate_passed",
        ).order_by(AgentEvent.id.desc())
    ).first()
    if latest_pass is None:
        return False
    latest_rev = session.exec(
        select(MapRevision).where(MapRevision.program_id == program.id)
        .order_by(MapRevision.id.desc())
    ).first()
    if latest_rev is None:
        return True
    # ties fail open: a missed nudge costs more than a spurious banner (advisory only)
    return latest_pass.created_at >= latest_rev.created_at
