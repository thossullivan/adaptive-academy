# src/adaptive_academy/engine/curriculum.py
import json

from adaptive_academy.engine.track_markdown import (
    DeliverableView,
    ItemView,
    PhaseView,
    SidebarView,
    TrackView,
)
from adaptive_academy.models import SourceDoc, TopicFoundation, TopicIntent


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
    """Guarantee every load-bearing concept is revisited across phases (code-enforced).

    - referenced in >=2 phases -> already spaced, no-op
    - referenced in exactly 1 phase p -> inject a 'revisit' write-item into the
      earliest later phase that doesn't already reference it
    - referenced in 0 phases -> inject a touch into the last phase
    - single phase total -> can't space; ensure at least one touch in that phase
    """
    for concept in sorted(load_bearing):
        refs = _phases_referencing(phases, concept)
        if len(refs) >= 2:
            continue
        if not phases:
            break
        if len(refs) == 1:
            p = refs[0]
            target = next((j for j in range(p + 1, len(phases))), None)
            if target is None:
                continue  # only earlier/this phase exists; cannot space
            phases[target].items.append(_revisit_item(concept))
        else:  # 0 references
            phases[-1].items.append(_revisit_item(concept))
    return phases


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def parse_curriculum_json(text: str, title: str) -> TrackView:
    data = json.loads(_strip_fences(text))
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


_CURRICULUM_SYSTEM = (
    "You are a CurriculumDirector for an ADVANCED, self-directed adult learner. "
    "Design an editable, phased learning Track from the foundation and reading list. "
    "Evidence-driven rules (follow them):\n"
    "- Default to LOW-ASSISTANCE, PROJECT/PROBLEM-FIRST items (expertise-reversal effect: "
    "high guidance harms experts). Lead with building/shipping, not lectures.\n"
    "- Give EXACTLY ONE shippable teaching artifact ('🎯 Ship') per phase "
    "(learning-by-teaching): a blog/repo/model/talk/ablation with acceptance criteria.\n"
    "- Revisit load-bearing prerequisites across LATER phases (spaced, not massed).\n"
    "- Treat deliberate-practice drills as SUPPORTING, never the spine.\n"
    "Respond with ONLY a JSON object: {\"overview\": str, \"phases\": [{\"title\": str, "
    "\"est_hours\": str, \"flags\": [\"optional\"|\"stretch\"|\"parallel_track\"], "
    "\"items\": [{\"type\": \"read\"|\"watch\"|\"build\"|\"write\", \"text\": str, "
    "\"concept_refs\": [str]}], \"deliverable\": {\"kind\": "
    "\"blog\"|\"repo\"|\"model\"|\"talk\"|\"ablation\", \"text\": str, "
    "\"acceptance_criteria\": [str]}}], \"sidebars\": [{\"kind\": "
    "\"math_refresh\"|\"reading_list\"|\"reference\", \"title\": str, \"body\": str}]}. "
    "Use the foundation's key concepts as item concept_refs. No prose outside the JSON."
)


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
    return _CURRICULUM_SYSTEM, "\n".join(lines)
