import json
import re
from dataclasses import dataclass, field

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


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def parse_remediation_json(text: str) -> RemediationDraft:
    d = json.loads(_strip_fences(text))
    revisit = d.get("revisit") or None
    return RemediationDraft(
        items=list(d.get("items", []) or []),
        revisit=revisit if isinstance(revisit, dict) else None,
    )


_REMEDIATE_SYSTEM = (
    "You are a CurriculumDirector in ADAPT MODE for an ADVANCED, self-directed adult "
    "learner who just revealed specific GAPS on one concept. Propose a SHORT, targeted "
    "remediation. Evidence-driven rules (follow them):\n"
    "- Default to LOW-ASSISTANCE, PROJECT/PROBLEM-FIRST items (expertise-reversal effect: "
    "high guidance harms experts). Each item must directly attack a NAMED gap.\n"
    "- Key the remediation to the learner's PRIOR-KNOWLEDGE level, not raw difficulty.\n"
    "- Deliberate-practice drills are SUPPORTING, never the spine.\n"
    "- Propose ONE item per listed gap, plus optionally ONE spaced 'revisit' for later.\n"
    'Respond with ONLY a JSON object: {"items": [{"type": "read"|"build"|"write", '
    '"text": str}], "revisit": {"text": str} | null}. No prose outside the JSON.'
)


def build_remediate_prompt(
    concept_name: str, gaps: list[str], level: str, *,
    foundation_overview: str = "", sources_summary: str = "",
) -> tuple[str, str]:
    lines = [
        f"CONCEPT: {concept_name}",
        f"LEARNER PRIOR-KNOWLEDGE LEVEL: {level}",
        "ASSESSED GAPS (one targeted item each):",
    ]
    lines += [f"- {g}" for g in gaps]
    if foundation_overview:
        lines += ["", f"FOUNDATION OVERVIEW: {foundation_overview}"]
    if sources_summary:
        lines += [f"SOURCES: {sources_summary}"]
    return _REMEDIATE_SYSTEM, "\n".join(lines)
