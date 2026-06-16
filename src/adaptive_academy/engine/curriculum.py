# src/adaptive_academy/engine/curriculum.py
from adaptive_academy.engine.track_markdown import ItemView, PhaseView


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
