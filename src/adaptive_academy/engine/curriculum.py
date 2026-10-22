# src/adaptive_academy/engine/curriculum.py
import json
from dataclasses import dataclass

from sqlmodel import Session, select

from adaptive_academy.engine import concept_names, graph
from adaptive_academy.jsonout import (
    dropped_summary,
    extract_json,
    require_list,
    require_object,
    str_items,
    text_items,
)
from adaptive_academy.engine.track_markdown import (
    DeliverableView,
    ItemView,
    PhaseView,
    SidebarView,
    TrackView,
)
from adaptive_academy.engine.runlock import exclusive_run
from adaptive_academy.llm.structured import structured_json
from adaptive_academy.llm.types import LLMClient, StructuredOutputError
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
# A one-phase track's single revisit item lists at most this many names in its text (its
# concept_refs still hold every concept it touches).
MAX_REVISIT_NAMES_SHOWN = 5


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


def _first_use(phases: list[PhaseView], dependents: set[str]) -> int | None:
    """The first phase that references something depending on the concept."""
    uses = [i for d in dependents for i in _phases_referencing(phases, d)]
    return min(uses) if uses else None


def _revisit_targets(n: int, p: int, first_use: int | None) -> list[int]:
    """Phases to try, in order, for the second touch of a concept the model put in phase p."""
    if first_use is not None and first_use < p:
        # the model introduced it after a dependent already used it: touch it earlier
        return list(range(first_use, -1, -1))
    return [*range(p + 1, n), *range(p - 1, -1, -1)]


def _intro_targets(n: int, first_use: int | None) -> list[int]:
    """Phases to try for the first touch of a concept the model never placed: just before
    its first dependent's phase, then that phase, then earlier — never after it."""
    if first_use is None:
        return list(range(n))
    return [i for i in (first_use - 1, first_use, *range(first_use - 2, -1, -1)) if i >= 0]


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
      with room (else the nearest earlier one); if a dependent already used it before p,
      in the nearest phase at or before that use instead
    - referenced in 0 phases -> two touches, placed only when both fit: the first just
      before the first phase that uses one of its dependents (never after it; the first
      phase if no dependent is used), the second in the nearest later phase with room
    - single phase total -> cannot space; ONE revisit item touches every unreferenced
      load-bearing concept (its concept_refs list them all)

    Bounded: no phase gets more than `cap` injected revisits (existing ones count), and a
    phase that already references a concept never gets a revisit of it. Concepts with the
    most dependents are placed first; what the cap leaves out is reported by `unspaced`.
    """
    if not phases:
        return phases
    dependents = dependents or {}
    order = sorted(load_bearing, key=lambda c: (-len(dependents.get(c, ())), c))
    if len(phases) == 1:
        missing = [c for c in order if not _phases_referencing(phases, c)]
        if missing:
            shown = ", ".join(missing[:MAX_REVISIT_NAMES_SHOWN])
            if len(missing) > MAX_REVISIT_NAMES_SHOWN:
                shown += f" and {len(missing) - MAX_REVISIT_NAMES_SHOWN} more"
            phases[0].items.append(ItemView(text=REVISIT_PREFIX + shown,
                                            type="write", concept_refs=missing))
        return phases
    n = len(phases)
    used = [sum(1 for it in p.items if _is_revisit(it)) for p in phases]

    def free(i: int) -> bool:
        return used[i] < cap

    def place(i: int, concept: str) -> None:
        phases[i].items.append(_revisit_item(concept))
        used[i] += 1

    for concept in order:
        refs = _phases_referencing(phases, concept)
        if len(refs) >= 2:
            continue
        first_use = _first_use(phases, dependents.get(concept, set()))
        if len(refs) == 1:
            target = next((i for i in _revisit_targets(n, refs[0], first_use)
                           if i != refs[0] and free(i)), None)
            if target is not None:
                place(target, concept)
            continue
        for first in (i for i in _intro_targets(n, first_use) if free(i)):
            second = next((i for i in range(first + 1, n) if free(i)), None)
            if second is not None:
                place(first, concept)
                place(second, concept)
                break
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


def _entries(value: object, path: str, dropped: list[str]) -> list[tuple[str, dict]]:
    """(path, entry) for each object in a JSON array; a non-array or non-object entry is
    recorded in `dropped` by its path and skipped."""
    if not value:
        return []
    if not isinstance(value, list):
        dropped.append(path)
        return []
    out: list[tuple[str, dict]] = []
    for i, entry in enumerate(value):
        if isinstance(entry, dict):
            out.append((f"{path}[{i}]", entry))
        else:
            dropped.append(f"{path}[{i}]")
    return out


def parse_curriculum_obj(data: object, title: str, *,
                         dropped: list[str] | None = None) -> TrackView:
    """The model's track as a TrackView, skipping malformed entries.

    The schema check (llm/schema_check.py) normally stops a wrongly shaped answer before it
    gets here; this is the defence behind it. A phase, item or sidebar that isn't an object
    (the live failure: a phase as a string) is skipped and its JSON path appended to
    `dropped`. An answer with nothing usable (not an object, `phases` not a list, or phases
    of which none is an object) is a StructuredOutputError, not an empty track. An empty
    `phases` list is the model's answer and is kept.
    """
    dropped = [] if dropped is None else dropped
    data = require_object(data, "curriculum")
    raw_phases = require_list(data, "phases", "curriculum")
    phases: list[PhaseView] = []
    for path, p in _entries(raw_phases, "$.phases", dropped):
        items = [
            ItemView(text=str(it.get("text", "")), type=str(it.get("type", "read")),
                     concept_refs=text_items(it.get("concept_refs")))
            for _, it in _entries(p.get("items"), f"{path}.items", dropped)
        ]
        d = p.get("deliverable") or None
        deliverable = None
        if isinstance(d, dict):
            deliverable = DeliverableView(
                text=str(d.get("text", "")), kind=str(d.get("kind", "blog")),
                acceptance_criteria=str_items(d.get("acceptance_criteria")))
        elif d is not None:
            dropped.append(f"{path}.deliverable")
        phases.append(PhaseView(
            title=str(p.get("title", "")), est_hours=str(p.get("est_hours", "")),
            flags=str_items(p.get("flags")), items=items, deliverable=deliverable))
    if raw_phases and not phases:
        raise StructuredOutputError(
            "malformed", f"curriculum: none of its {len(raw_phases)} phases is an object")
    sidebars = [
        SidebarView(kind=str(s.get("kind", "reference")), title=str(s.get("title", "")),
                    body=str(s.get("body", "")))
        for _, s in _entries(data.get("sidebars"), "$.sidebars", dropped)
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


def _topic_has_concepts(session: Session, topic_id: int) -> bool:
    return session.exec(
        select(Concept.id).join(Track).where(Track.topic_id == topic_id)).first() is not None


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
    # answer: repair the names first, so the prompt, the Concept rows and the anchors
    # (which resolve against foundation.key_concepts) all agree on the short names. The
    # stored foundation is rewritten only together with the new track (below), and never
    # once the topic has Concept rows: those rows, their anchors and alias groups match the
    # stored names exactly, and renaming under them would break every lookup.
    key_concepts = list(foundation.key_concepts)
    prerequisite_map = dict(foundation.prerequisite_map)
    renamed: dict[str, str] = {}
    fix = concept_names.repair_names(key_concepts, prerequisite_map)
    repair_foundation = False
    if not fix.report.passed:
        if _topic_has_concepts(session, topic.id):
            emit("concepts:repair_skipped",
                 "WARN " + ",".join(dict.fromkeys(fix.report.failed_ids))
                 + ": topic already has concepts under these names; left unchanged")
        else:
            key_concepts, prerequisite_map, renamed = (
                fix.key_concepts, fix.prerequisite_map, fix.renamed)
            repair_foundation = True
            emit("concepts:repaired", fix.summary())
    emit("prompt", CURRICULUM.tag)
    prompt_foundation = TopicFoundation(
        topic_id=foundation.topic_id, overview=foundation.overview,
        key_concepts=key_concepts, prerequisite_map=prerequisite_map)  # never added
    system, user = build_curriculum_prompt(topic.title, intent, prompt_foundation, sources)
    session.commit()  # release the lock before the LLM call (F5)
    data = structured_json(
        llm, system, [{"role": "user", "content": user}],
        schema=CURRICULUM_SCHEMA, tool_name="emit_track")
    malformed: list[str] = []
    draft = parse_curriculum_obj(data, title=topic.title, dropped=malformed)
    if malformed:
        emit("curriculum:malformed", dropped_summary(malformed))

    canonicalize_concept_refs(draft.phases, key_concepts, renamed)
    dependents = dependents_of(prerequisite_map, key_concepts)
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

    if repair_foundation:  # committed with the track below, so never without it
        foundation.key_concepts = key_concepts
        foundation.prerequisite_map = prerequisite_map
        session.add(foundation)
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
    for name in key_concepts:
        is_lb = name in lb
        lb_count += int(is_lb)
        concept = Concept(track_id=track.id, name=name, is_load_bearing=is_lb)
        session.add(concept)
        session.commit()
        session.refresh(concept)
        session.add(KnowledgeEstimate(concept_id=concept.id, level="high", confidence=0.5))

    concepts = session.exec(select(Concept).where(Concept.track_id == track.id)).all()
    pairs, unresolved = graph.edges_from_prerequisite_map(prerequisite_map, concepts)
    for topic_track in session.exec(select(Track).where(Track.topic_id == topic.id)).all():
        graph.invalidate_track_edges(session, topic_track.id)
    inserted = graph.insert_edges(session, pairs, kind="prerequisite", origin="researcher",
                                  origin_ref=f"foundation:{topic.id}")
    emit("graph:edges", f"{inserted} edges, {len(unresolved)} unresolved")
    emit("curriculum:concepts", f"{len(key_concepts)} concepts, {lb_count} load-bearing")

    emit("curriculum:done", f"track {track.id}")
    session.commit()
    session.refresh(track)
    return CurriculumResult(track=track, events=events)
