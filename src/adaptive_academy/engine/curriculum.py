# src/adaptive_academy/engine/curriculum.py
import json
from dataclasses import dataclass

from sqlmodel import Session, select

from adaptive_academy.engine import graph
from adaptive_academy.jsonout import extract_json
from adaptive_academy.engine.track_markdown import (
    DeliverableView,
    ItemView,
    PhaseView,
    SidebarView,
    TrackView,
)
from adaptive_academy.engine.runlock import exclusive_run
from adaptive_academy.llm.structured import structured_json
from adaptive_academy.llm.types import LLMClient
from adaptive_academy.prompts import CURRICULUM
from adaptive_academy.models import (
    AgentEvent,
    Concept,
    Deliverable,
    Item,
    KnowledgeEstimate,
    Phase,
    Sidebar,
    SourceDoc,
    Topic,
    TopicFoundation,
    TopicIntent,
    Track,
)


def load_bearing_concepts(prerequisite_map: dict) -> set[str]:
    """A concept is load-bearing iff something depends on it (it appears as a
    prerequisite in any value list). This is the signal the spaced-revisit pass keys on.
    """
    lb: set[str] = set()
    for prereqs in prerequisite_map.values():
        for name in prereqs or []:
            if isinstance(name, str) and name:
                lb.add(name)
    return lb


def _phases_referencing(phases: list[PhaseView], concept: str) -> list[int]:
    return [i for i, p in enumerate(phases)
            if any(concept in it.concept_refs for it in p.items)]


def _revisit_item(concept: str) -> ItemView:
    return ItemView(text=f"Revisit & self-explain: {concept}", type="write",
                    concept_refs=[concept])


def insert_spaced_revisits(phases: list[PhaseView], load_bearing: set[str]) -> list[PhaseView]:
    """Guarantee every load-bearing concept spans >=2 phases (code-enforced spacing).

    Whenever at least two phases exist, every load-bearing concept ends up referenced
    in >=2 distinct phases (the evidence rule: spaced, not massed). Idempotent.

    - referenced in >=2 phases -> already spaced, no-op
    - referenced in exactly 1 phase p -> inject a 'revisit' write-item into a DIFFERENT
      phase (the next one if it exists, else the previous), so it spans two
    - referenced in 0 phases -> inject into the first and last phases (two distinct)
    - single phase total -> cannot space; ensure at least one touch in that phase
    """
    for concept in sorted(load_bearing):
        refs = _phases_referencing(phases, concept)
        if len(refs) >= 2:
            continue
        if not phases:
            break
        if len(phases) == 1:
            if not refs:  # cannot space with one phase; at least touch it once
                phases[0].items.append(_revisit_item(concept))
            continue
        if len(refs) == 1:
            p = refs[0]
            other = p + 1 if p + 1 < len(phases) else p - 1  # a different existing phase
            phases[other].items.append(_revisit_item(concept))
        else:  # 0 references, >=2 phases -> two distinct touches
            phases[0].items.append(_revisit_item(concept))
            phases[-1].items.append(_revisit_item(concept))
    return phases



# JSON Schema for strict-tool generation (sent via llm/strict_schema.py) — guarantees the track comes back well-shaped.
CURRICULUM_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "overview": {"type": "string"},
        "phases": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "est_hours": {"type": "string"},
                    "flags": {"type": "array", "items": {
                        "type": "string", "enum": ["optional", "stretch", "parallel_track"]}},
                    "items": {"type": "array", "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["read", "watch", "build", "write"]},
                            "text": {"type": "string"},
                            "concept_refs": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["type", "text"],
                    }},
                    "deliverable": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string",
                                     "enum": ["blog", "repo", "model", "talk", "ablation"]},
                            "text": {"type": "string"},
                            "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["kind", "text"],
                    },
                },
                "required": ["title", "items", "deliverable"],
            },
        },
        "sidebars": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["math_refresh", "reading_list", "reference"]},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["kind", "title", "body"],
        }},
    },
    "required": ["overview", "phases"],
}


def parse_curriculum_json(text: str, title: str) -> TrackView:
    return parse_curriculum_obj(json.loads(extract_json(text)), title)


def parse_curriculum_obj(data: dict, title: str) -> TrackView:
    phases: list[PhaseView] = []
    for p in data.get("phases", []) or []:
        items = [
            ItemView(text=str(it.get("text", "")), type=str(it.get("type", "read")),
                     concept_refs=list(it.get("concept_refs", []) or []))
            for it in (p.get("items", []) or [])
        ]
        d = p.get("deliverable") or None
        deliverable = None
        if d:
            deliverable = DeliverableView(
                text=str(d.get("text", "")), kind=str(d.get("kind", "blog")),
                acceptance_criteria=list(d.get("acceptance_criteria", []) or []))
        phases.append(PhaseView(
            title=str(p.get("title", "")), est_hours=str(p.get("est_hours", "")),
            flags=list(p.get("flags", []) or []), items=items, deliverable=deliverable))
    sidebars = [
        SidebarView(kind=str(s.get("kind", "reference")), title=str(s.get("title", "")),
                    body=str(s.get("body", "")))
        for s in (data.get("sidebars", []) or [])
    ]
    return TrackView(title=title, overview=str(data.get("overview", "")),
                     phases=phases, sidebars=sidebars)


def build_curriculum_prompt(
    topic_title: str, intent: TopicIntent, foundation: TopicFoundation,
    sources: list[SourceDoc],
) -> tuple[str, str]:
    lines = [
        f"TOPIC: {topic_title}",
        f"GOAL: {intent.goal}",
        f"PRIOR KNOWLEDGE: {intent.prior_knowledge}",
        f"TIME BUDGET: {intent.time_budget}",
        "",
        f"FOUNDATION OVERVIEW: {foundation.overview}",
        f"KEY CONCEPTS: {', '.join(foundation.key_concepts)}",
        f"PREREQUISITE MAP: {foundation.prerequisite_map}",
        "",
        "ACCEPTED READING LIST:",
    ]
    for s in sources:
        lines.append(f"- [{s.tier}] {s.title} ({s.url}) — {s.summary}".rstrip(" —"))
    return CURRICULUM, "\n".join(lines)


@dataclass
class CurriculumResult:
    track: Track
    events: list[AgentEvent]


def generate_curriculum(
    session: Session,
    topic: Topic,
    intent: TopicIntent,
    foundation: TopicFoundation,
    sources: list[SourceDoc],
    *,
    llm: LLMClient,
) -> CurriculumResult:
    """Single LLM call -> TrackView; enforce spacing; persist Track/Phase/Item/
    Deliverable/Sidebar/Concept(+estimate); trace; return.

    Raises `RunInProgress` when curriculum generation for this topic is already running.
    """
    with exclusive_run(f"curriculum:{topic.id}"):
        return _generate_curriculum_locked(session, topic, intent, foundation, sources, llm=llm)


def _generate_curriculum_locked(
    session: Session,
    topic: Topic,
    intent: TopicIntent,
    foundation: TopicFoundation,
    sources: list[SourceDoc],
    *,
    llm: LLMClient,
) -> CurriculumResult:
    events: list[AgentEvent] = []

    def emit(kind: str, detail: str = "") -> None:
        ev = AgentEvent(topic_id=topic.id, kind=kind, detail=detail)
        session.add(ev)
        events.append(ev)

    emit("curriculum:plan", f"{len(foundation.key_concepts)} concepts, {len(sources)} sources")
    emit("prompt", CURRICULUM.tag)
    system, user = build_curriculum_prompt(topic.title, intent, foundation, sources)
    session.commit()  # release the lock before the LLM call (F5)
    data = structured_json(
        llm, system, [{"role": "user", "content": user}],
        schema=CURRICULUM_SCHEMA, tool_name="emit_track")
    draft = parse_curriculum_obj(data, title=topic.title)

    lb = load_bearing_concepts(foundation.prerequisite_map)
    before = sum(len(p.items) for p in draft.phases)
    insert_spaced_revisits(draft.phases, lb)
    revisits = sum(len(p.items) for p in draft.phases) - before
    emit("curriculum:generated", f"{len(draft.phases)} phases")
    if revisits:
        emit("curriculum:spaced", f"{revisits} revisit item(s) injected")

    track = Track(topic_id=topic.id, title=topic.title, overview=draft.overview)
    session.add(track)
    session.commit()
    session.refresh(track)

    for pi, pv in enumerate(draft.phases):
        phase = Phase(track_id=track.id, title=pv.title, position=pi,
                      est_hours=pv.est_hours, flags=pv.flags)
        session.add(phase)
        session.commit()
        session.refresh(phase)
        for ii, iv in enumerate(pv.items):
            session.add(Item(phase_id=phase.id, text=iv.text, type=iv.type,
                             position=ii, concept_refs=iv.concept_refs))
        if pv.deliverable:
            session.add(Deliverable(phase_id=phase.id, kind=pv.deliverable.kind,
                                    text=pv.deliverable.text,
                                    acceptance_criteria=pv.deliverable.acceptance_criteria))
    for si, sv in enumerate(draft.sidebars):
        session.add(Sidebar(track_id=track.id, kind=sv.kind, title=sv.title,
                            body=sv.body, position=si))

    lb_count = 0
    for name in foundation.key_concepts:
        is_lb = name in lb
        lb_count += int(is_lb)
        concept = Concept(track_id=track.id, name=name, is_load_bearing=is_lb)
        session.add(concept)
        session.commit()
        session.refresh(concept)
        session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.5))

    concepts = session.exec(select(Concept).where(Concept.track_id == track.id)).all()
    pairs, unresolved = graph.edges_from_prerequisite_map(foundation.prerequisite_map, concepts)
    for topic_track in session.exec(select(Track).where(Track.topic_id == topic.id)).all():
        graph.invalidate_track_edges(session, topic_track.id)
    inserted = graph.insert_edges(session, pairs, kind="prerequisite", origin="researcher",
                                  origin_ref=f"foundation:{topic.id}")
    emit("graph:edges", f"{inserted} edges, {len(unresolved)} unresolved")
    emit("curriculum:concepts", f"{len(foundation.key_concepts)} concepts, {lb_count} load-bearing")

    emit("curriculum:done", f"track {track.id}")
    session.commit()
    session.refresh(track)
    return CurriculumResult(track=track, events=events)
