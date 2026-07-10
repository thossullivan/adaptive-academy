"""Cross-topic knowledge carryover inside a Program (spec §4.4).

After a program topic's curriculum materializes concepts, link them by normalized name
to prior concepts in the same program (ConceptAlias groups). A matched concept's
KnowledgeEstimate is seeded from the group's most recently assessed member instead of
the cold default — the Tutor opens at the right assistance level and the curriculum
skips what the learner verifiably kept. Name-match only (Plan 6 pattern); LLM-assisted
matching is deferred until this demonstrably misses.
"""

from dataclasses import dataclass, field

from sqlmodel import Session, select

from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    ConceptAlias,
    KnowledgeEstimate,
    Milestone,
    ProgramTopicLink,
    Track,
)


def normalize_name(name: str) -> str:
    return name.strip().casefold()


@dataclass
class AliasResult:
    registered: int = 0
    seeded: list[tuple[int, str]] = field(default_factory=list)  # (concept_id, level)


def _program_for_topic(session: Session, topic_id: int) -> int | None:
    link = session.exec(
        select(ProgramTopicLink).where(
            ProgramTopicLink.topic_id == topic_id,
            ProgramTopicLink.status == "started",
        )
    ).first()
    if link is None:
        return None
    milestone = session.get(Milestone, link.milestone_id)
    return milestone.program_id if milestone else None


def group_level(session: Session, member_ids: list[int]) -> str | None:
    """Level of the group's most recently assessed member; falls back to the
    newest member's estimate when nothing was ever assessed."""
    if not member_ids:
        return None
    latest = session.exec(
        select(Assessment)
        .where(Assessment.concept_id.in_(member_ids))
        .order_by(Assessment.id.desc())
    ).first()
    source_id = latest.concept_id if latest else max(member_ids)
    est = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == source_id)
    ).first()
    return est.level if est else None


def apply_program_aliases(session: Session, topic_id: int) -> AliasResult:
    """Register this topic's concepts into the program's alias groups; seed estimates
    for matches. Idempotent: concepts already aliased are skipped. No-op for topics
    outside a program."""
    program_id = _program_for_topic(session, topic_id)
    if program_id is None:
        return AliasResult()

    concepts = session.exec(
        select(Concept).join(Track).where(Track.topic_id == topic_id)
    ).all()
    result = AliasResult()
    for c in concepts:
        already = session.exec(
            select(ConceptAlias).where(ConceptAlias.concept_id == c.id)
        ).first()
        if already is not None:
            continue
        canonical = normalize_name(c.name)
        group = session.exec(
            select(ConceptAlias).where(
                ConceptAlias.program_id == program_id,
                ConceptAlias.canonical_name == canonical,
            )
        ).all()
        if group:
            level = group_level(session, [g.concept_id for g in group])
            est = session.exec(
                select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == c.id)
            ).first()
            if level is not None and est is not None and est.level != level:
                est.level = level
                session.add(est)
                result.seeded.append((c.id, level))
        session.add(ConceptAlias(program_id=program_id, canonical_name=canonical,
                                 concept_id=c.id))
        result.registered += 1

    if result.registered:
        session.add(AgentEvent(
            topic_id=topic_id, kind="program:alias",
            detail=f"{result.registered} registered, {len(result.seeded)} seeded"))
    session.commit()
    return result
