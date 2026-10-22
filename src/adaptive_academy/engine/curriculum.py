# src/adaptive_academy/engine/curriculum.py
import json
from dataclasses import dataclass

from sqlmodel import Session, select

from adaptive_academy.engine import concept_names, graph
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


REVISIT_PREFIX = "Revisit & self-explain: "
# At most this many app-injected revisit items per phase. The prompt keeps a phase to at most
# 6 items; spacing is meant to thread a few load-bearing prerequisites through the track, and
# a phase of 25 revisits (the live failure) is massed practice, the opposite of spacing.
MAX_REVISITS_PER_PHASE = 2


def _norm(name: str) -> str:
    return name.strip().casefold()


def _key_lookup(key_concepts: list[str]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for name in key_concepts:
        if isinstance(name, str) and name.strip():
            lookup.setdefault(_norm(name), name)
    return lookup


def dependents_of(prerequisite_map: dict, key_concepts: list[str]) -> dict[str, set[str]]:
    """Key concept -> the concepts that list it as a prerequisite.

    Names resolve to key concepts exactly or case/space-insensitively. A prerequisite that
    is not a key concept is left out: it never becomes a Concept row, so a revisit of it
    has nothing to self-explain against or to grade. A self-loop is not a dependency.
    """
    lookup = _key_lookup(key_concepts)
    out: dict[str, set[str]] = {}
    for source, prereqs in (prerequisite_map or {}).items():
        if not isinstance(source, str) or not isinstance(prereqs, list):
            continue
        dependent = lookup.get(_norm(source), source)
        for name in prereqs:
            prereq = lookup.get(_norm(name)) if isinstance(name, str) else None
            if prereq is not None and prereq != dependent:
                out.setdefault(prereq, set()).add(dependent)
    return out


def load_bearing_concepts(prerequisite_map: dict,
                          key_concepts: list[str] | None = None) -> set[str]:
    """A concept is load-bearing iff something depends on it (it appears as a
    prerequisite in any value list). This is the signal the spaced-revisit pass keys on.

    With `key_concepts`, only generated concepts count (spec §2.3: "a generated Concept is
    load-bearing iff it appears as a prerequisite"), under their key-concept spelling.
    """
    if key_concepts is not None:
        return set(dependents_of(prerequisite_map, key_concepts))
    lb: set[str] = set()
    for prereqs in prerequisite_map.values():
        for name in prereqs or []:
            if isinstance(name, str) and name:
                lb.add(name)
    return lb


def canonicalize_concept_refs(phases: list[PhaseView], key_concepts: list[str],
                              renamed: dict[str, str] | None = None) -> None:
    """Rewrite item concept_refs to the key concepts' exact names, in place.

    The model may spell a key concept in another case, or (for a foundation whose names
    were repaired) use a pre-repair name. Coverage, artifact review and remediation all
    match concept_refs to Concept names exactly, so an unmatched spelling read as "never
    referenced" and drew two revisit items. Unknown refs are kept; duplicates dropped.
    """
    lookup = _key_lookup(key_concepts)
    for old, new in (renamed or {}).items():
        lookup.setdefault(_norm(old), lookup.get(_norm(new), new))
    for phase in phases:
        for item in phase.items:
            refs: list[str] = []
            for ref in item.concept_refs:
                if not isinstance(ref, str):
                    continue
                name = lookup.get(_norm(ref), ref)
                if name not in refs:
                    refs.append(name)
            item.concept_refs = refs


def _phases_referencing(phases: list[PhaseView], concept: str) -> list[int]:
    return [i for i, p in enumerate(phases)
            if any(concept in it.concept_refs for it in p.items)]


def _revisit_item(concept: str) -> ItemView:
    return ItemView(text=f"{REVISIT_PREFIX}{concept}", type="write",
                    concept_refs=[concept])


def _is_revisit(item: ItemView) -> bool:
    return item.text.startswith(REVISIT_PREFIX)


def _revisit_targets(phases: list[PhaseView], refs: list[int],
                     dependents: set[str]) -> list[int]:
    """Phases to try, in order, for a concept's missing touches."""
    if refs:
        start = refs[0] + 1  # spaced: the phases after its first touch, then before it
    else:
        uses = [i for d in dependents for i in _phases_referencing(phases, d)]
        # a prerequisite the model never placed: just before its first dependent uses it
        start = max(min(uses) - 1, 0) if uses else 0
    return [*range(start, len(phases)), *range(start - 1, -1, -1)]


def insert_spaced_revisits(
    phases: list[PhaseView],
    load_bearing: set[str],
    dependents: dict[str, set[str]] | None = None,
    *,
    cap: int = MAX_REVISITS_PER_PHASE,
) -> list[PhaseView]:
    """Space every load-bearing concept across >=2 phases (code-enforced), bounded.

    Spec §2.2: whenever at least two phases exist, a load-bearing concept should be
    referenced in >=2 distinct phases (the evidence rule: spaced, not massed). Idempotent.

    - referenced in >=2 phases -> already spaced, no-op
    - referenced in exactly 1 phase p -> a 'revisit' write-item in the nearest later phase
      with room (else the nearest earlier one)
    - referenced in 0 phases -> two touches starting just before the first phase that uses
      one of its dependents (the first phase if none does), in consecutive phases with room
    - single phase total -> cannot space; at least one touch in that phase

    Bounded: no phase gets more than `cap` injected revisits (existing ones count), and a
    phase that already references a concept never gets a revisit of it. Concepts with the
    most dependents are placed first; what the cap leaves out is reported by `unspaced`.
    """
    if not phases:
        return phases
    dependents = dependents or {}
    used = [sum(1 for it in p.items if _is_revisit(it)) for p in phases]
    want = 1 if len(phases) == 1 else 2
    for concept in sorted(load_bearing, key=lambda c: (-len(dependents.get(c, ())), c)):
        refs = _phases_referencing(phases, concept)
        need = want - len(refs)
        if need <= 0:
            continue
        for target in _revisit_targets(phases, refs, dependents.get(concept, set())):
            if need == 0:
                break
            if target in refs or used[target] >= cap:
                continue
            phases[target].items.append(_revisit_item(concept))
            used[target] += 1
            refs.append(target)
            need -= 1
    return phases


def unspaced(phases: list[PhaseView], load_bearing: set[str]) -> list[str]:
    """Load-bearing concepts that still span fewer phases than spacing asks for."""
    want = 1 if len(phases) == 1 else 2
    return sorted(c for c in load_bearing if len(_phases_referencing(phases, c)) < want)



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
    # Concept names become Concept rows, Tutor headings and probe text here. Research checks
    # them, but a foundation stored before that check (or edited) may still state its
    # answer: repair it in place first, so the prompt, the Concept rows and the anchors
    # (which resolve against foundation.key_concepts) all agree on the short names.
    renamed: dict[str, str] = {}
    fix = concept_names.repair_names(foundation.key_concepts, foundation.prerequisite_map)
    if not fix.report.passed:
        foundation.key_concepts = fix.key_concepts
        foundation.prerequisite_map = fix.prerequisite_map
        session.add(foundation)
        renamed = fix.renamed
        emit("concepts:repaired", fix.summary())
    emit("prompt", CURRICULUM.tag)
    system, user = build_curriculum_prompt(topic.title, intent, foundation, sources)
    session.commit()  # release the lock before the LLM call (F5)
    data = structured_json(
        llm, system, [{"role": "user", "content": user}],
        schema=CURRICULUM_SCHEMA, tool_name="emit_track")
    draft = parse_curriculum_obj(data, title=topic.title)

    canonicalize_concept_refs(draft.phases, foundation.key_concepts, renamed)
    dependents = dependents_of(foundation.prerequisite_map, foundation.key_concepts)
    lb = set(dependents)
    before = sum(len(p.items) for p in draft.phases)
    insert_spaced_revisits(draft.phases, lb, dependents)
    revisits = sum(len(p.items) for p in draft.phases) - before
    emit("curriculum:generated", f"{len(draft.phases)} phases")
    if revisits:
        emit("curriculum:spaced", f"{revisits} revisit item(s) injected")
    left = unspaced(draft.phases, lb)
    if left and draft.phases:
        emit("curriculum:unspaced",
             f"{len(left)} load-bearing concept(s) in fewer than 2 phases "
             f"(cap {MAX_REVISITS_PER_PHASE} revisits/phase): {', '.join(left[:5])}"
             + (" …" if len(left) > 5 else ""))

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
