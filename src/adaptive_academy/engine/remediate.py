import re
from dataclasses import dataclass

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
