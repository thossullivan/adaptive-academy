"""Map Revision — learnings-aware re-research for a Program's milestone map.

This module owns: the deterministic learnings digest (this task), and (later
tasks) the 3-angle freshness pass, diff synthesis, and per-change apply logic.
Spec: docs/superpowers/specs/2026-07-10-map-revision.md
"""

from collections import Counter

from sqlmodel import Session, select

from adaptive_academy.engine.aliases import group_level
from adaptive_academy.engine.gates import evaluate_concept, milestone_load_bearing
from adaptive_academy.models import (
    Assessment,
    ConceptAlias,
    Milestone,
    Program,
    ProgramTopicLink,
)


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
