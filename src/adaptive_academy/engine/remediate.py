import json
import re
from dataclasses import dataclass, field

from sqlmodel import Session, select

from adaptive_academy.engine import graph
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.prompts import REMEDIATE
from adaptive_academy.models import (
    AgentEvent,
    Assessment,
    Concept,
    Item,
    KnowledgeEstimate,
    Phase,
    SourceDoc,
    TopicFoundation,
    Track,
)

_VALID_TYPES = {"read", "build", "write", "watch"}
_WS = re.compile(r"\s+")


def gap_key(gap: str) -> str:
    """Stable idempotency signature for a gap string (lowercased, ws-collapsed, trimmed)."""
    return _WS.sub(" ", gap.strip().lower())


@dataclass
class PlacedItem:
    text: str
    type: str
    concept_refs: list[str]
    remediation_key: str
    added_by: str = "remediation"


def _item_type(raw) -> str:
    t = str(raw or "").strip().lower()
    return t if t in _VALID_TYPES else "build"


def plan_remediation_items(
    proposed: list[dict], concept_name: str, gaps: list[str], covered: set[str],
) -> list[PlacedItem]:
    """One remediation item per *uncovered* gap (idempotent), in gap order.

    `proposed` is the LLM's item list; item i is matched to uncovered gap i. When the
    LLM returns fewer items than uncovered gaps, fall back to a deterministic template
    so every uncovered gap is addressed and no item has empty text.
    """
    out: list[PlacedItem] = []
    uncovered = [g for g in gaps if gap_key(g) not in covered]
    for i, gap in enumerate(uncovered):
        src = proposed[i] if i < len(proposed) else {}
        text = str(src.get("text") or "").strip() or f"Remediate: {gap} (re: {concept_name})"
        out.append(PlacedItem(text=text, type=_item_type(src.get("type")),
                              concept_refs=[concept_name], remediation_key=gap_key(gap)))
    return out


def choose_target_phase(phase_item_statuses: list[list[str]]) -> int:
    """Index of the 'current' phase: earliest with a non-`done` item (or no items);
    else the last phase. Empty input is invalid (caller guarantees >=1 phase)."""
    for i, statuses in enumerate(phase_item_statuses):
        if not statuses or any(s != "done" for s in statuses):
            return i
    return len(phase_item_statuses) - 1


@dataclass
class RemediationDraft:
    items: list[dict] = field(default_factory=list)
    revisit: dict | None = None



def parse_remediation_json(text: str) -> RemediationDraft:
    d = json.loads(extract_json(text))
    revisit = d.get("revisit") or None
    return RemediationDraft(
        items=list(d.get("items", []) or []),
        revisit=revisit if isinstance(revisit, dict) else None,
    )


def build_remediate_prompt(
    concept_name: str, gaps: list[str], level: str, *,
    ancestor_name: str = "", foundation_overview: str = "",
    sources_summary: str = "",
) -> tuple[str, str]:
    lines = [
        f"CONCEPT: {concept_name}",
    ]
    if ancestor_name:
        lines.append(f"ANCESTOR: {ancestor_name}")
    lines += [
        f"LEARNER PRIOR-KNOWLEDGE LEVEL: {level}",
        "ASSESSED GAPS (one targeted item each):",
    ]
    lines += [f"- {g}" for g in gaps]
    if foundation_overview:
        lines += ["", f"FOUNDATION OVERVIEW: {foundation_overview}"]
    if sources_summary:
        lines += [f"SOURCES: {sources_summary}"]
    return REMEDIATE, "\n".join(lines)


class RemediationError(Exception):
    """No assessment to remediate from (route maps to HTTP 400)."""


@dataclass
class RemediationResult:
    items: list[Item]
    events: list[AgentEvent]


def _latest_assessment(session: Session, concept_id: int,
                       assessment_id: int | None) -> Assessment | None:
    if assessment_id is not None:
        return session.get(Assessment, assessment_id)
    return session.exec(
        select(Assessment).where(Assessment.concept_id == concept_id)
        .order_by(Assessment.id.desc())).first()


def _covered_keys(session: Session, track_id: int, concept_name: str) -> set[str]:
    """remediation_keys of still-OPEN remediation items referencing this concept."""
    rows = session.exec(
        select(Item).join(Phase).where(Phase.track_id == track_id)).all()
    return {
        it.remediation_key for it in rows
        if it.added_by == "remediation" and it.status != "done"
        and concept_name in (it.concept_refs or [])
    }


def _earliest_concept_phase(
    session: Session,
    concept: Concept,
) -> tuple[list[Phase], int] | None:
    """Return the concept's earliest referenced phase, then its track's first phase."""
    phases = session.exec(
        select(Phase)
        .where(Phase.track_id == concept.track_id)
        .order_by(Phase.position)
    ).all()
    if not phases:
        return None
    for index, phase in enumerate(phases):
        items = session.exec(select(Item).where(Item.phase_id == phase.id)).all()
        if any(concept.name in (item.concept_refs or []) for item in items):
            return phases, index
    return phases, 0


def remediate_concept(session: Session, concept: Concept, *,
                      llm: LLMClient, assessment_id: int | None = None) -> RemediationResult:
    track = session.get(Track, concept.track_id)
    topic_id = track.topic_id
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic_id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    assessment = _latest_assessment(session, concept.id, assessment_id)
    if assessment is None:
        raise RemediationError("no assessment to remediate from")

    covered = _covered_keys(session, track.id, concept.name)
    open_gaps = [g for g in (assessment.gaps or []) if gap_key(g) not in covered]
    emit("remediate:probe", f"{len(open_gaps)} open gap(s)")
    if not open_gaps:
        emit("remediate:done", "nothing to remediate")
        session.commit()
        return RemediationResult(items=[], events=events)

    phases = session.exec(
        select(Phase).where(Phase.track_id == track.id).order_by(Phase.position)).all()
    if not phases:
        raise RemediationError("track has no phases to remediate into")

    estimate = session.exec(
        select(KnowledgeEstimate).where(KnowledgeEstimate.concept_id == concept.id)).first()
    level = estimate.level if estimate else "high"
    ancestor_name = ""
    ancestor_target: tuple[list[Phase], int] | None = None
    weakest = graph.weakest_ancestor(session, concept.id)
    if weakest is not None:
        ancestor = session.get(Concept, weakest[0])
        ancestor_estimate = session.exec(
            select(KnowledgeEstimate).where(
                KnowledgeEstimate.concept_id == weakest[0]
            )
        ).first()
        ancestor_level = ancestor_estimate.level if ancestor_estimate else None
        target_rank = graph.LEVEL_ORDER.get(level, len(graph.LEVEL_ORDER))
        ancestor_rank = (
            graph.LEVEL_ORDER.get(ancestor_level, -1)
            if ancestor_level is not None
            else -1
        )
        if ancestor is not None and ancestor_rank < target_rank:
            ancestor_name = ancestor.name
            ancestor_target = _earliest_concept_phase(session, ancestor)
            emit(
                "remediate:ancestor",
                f"{ancestor.name} (concept {ancestor.id}, level {ancestor_level or 'unknown'})",
            )
    foundation = session.exec(
        select(TopicFoundation).where(TopicFoundation.topic_id == topic_id)).first()
    sources = session.exec(
        select(SourceDoc).where(SourceDoc.topic_id == topic_id,
                                SourceDoc.status == "accepted")).all()
    sources_summary = "; ".join(s.title for s in sources)

    system, user = build_remediate_prompt(
        concept.name, open_gaps, level,
        ancestor_name=ancestor_name,
        foundation_overview=(foundation.overview if foundation else ""),
        sources_summary=sources_summary)
    emit("prompt", REMEDIATE.tag)
    draft = parse_remediation_json(
        llm.complete(system=system, messages=[{"role": "user", "content": user}], tools=[]).text)

    planned = plan_remediation_items(draft.items, concept.name, open_gaps, covered)
    emit("remediate:generated", f"{len(planned)} item(s)")

    placement_phases = ancestor_target[0] if ancestor_target is not None else phases
    statuses = [
        [
            item.status
            for item in session.exec(
                select(Item).where(Item.phase_id == phase.id)
            ).all()
        ]
        for phase in placement_phases
    ]
    target_idx = (
        ancestor_target[1]
        if ancestor_target is not None
        else choose_target_phase(statuses)
    )
    target = placement_phases[target_idx]
    base_pos = len(statuses[target_idx])

    created: list[Item] = []
    for offset, pi in enumerate(planned):
        item = Item(phase_id=target.id, text=pi.text, type=pi.type,
                    position=base_pos + offset, concept_refs=pi.concept_refs,
                    added_by="remediation", remediation_key=pi.remediation_key)
        session.add(item)
        created.append(item)
    emit("remediate:placed", f"phase {target.position}")

    revisit_key = f"revisit:{gap_key(concept.name)}"
    if draft.revisit and revisit_key not in covered:
        later = (
            placement_phases[target_idx + 1]
            if target_idx + 1 < len(placement_phases)
            else target
        )
        rtext = str(draft.revisit.get("text") or "").strip() or \
            f"Revisit & self-explain: {concept.name}"
        rpos = len(session.exec(select(Item).where(Item.phase_id == later.id)).all())
        ritem = Item(phase_id=later.id, text=rtext, type="write", position=rpos,
                     concept_refs=[concept.name], added_by="remediation",
                     remediation_key=revisit_key)
        session.add(ritem)
        created.append(ritem)

    emit("remediate:done", f"concept {concept.id}")
    session.commit()
    for it in created:
        session.refresh(it)
    return RemediationResult(items=created, events=events)
