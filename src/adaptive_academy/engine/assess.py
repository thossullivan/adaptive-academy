import json
from dataclasses import dataclass, field

_OMISSION_PENALTY = 0.15


def level_from_score(score: float) -> tuple[str, float]:
    """Map an anchored score (0..1) to a KnowledgeEstimate level + confidence.

    Thresholds are empirical (tune here): >=0.75 high, >=0.45 medium, else low.
    """
    s = max(0.0, min(1.0, score))
    level = "high" if s >= 0.75 else "medium" if s >= 0.45 else "low"
    return level, round(s, 2)


def compute_delta(score: float, baseline_score: float | None) -> float | None:
    if baseline_score is None:
        return None
    return round(score - baseline_score, 4)


def apply_rules_checks(response: str, must_include: list[str], weak_signs: list[str]) -> list[str]:
    """Deterministic anchor checks (§2.3): the LLM grader cannot paper over these."""
    text = response.lower()
    gaps: list[str] = []
    for term in must_include:
        if term and term.lower() not in text:
            gaps.append(f"omitted required element: {term}")
    for sign in weak_signs:
        if sign and sign.lower() in text:
            gaps.append(f"contains likely misconception: {sign}")
    return gaps


def penalize_score(llm_score: float, rules_gaps: list[str]) -> float:
    """Penalize the LLM score for each omitted required element (anti-sycophancy)."""
    omissions = sum(1 for g in rules_gaps if g.startswith("omitted required element"))
    return round(max(0.0, min(1.0, llm_score) - _OMISSION_PENALTY * omissions), 4)


@dataclass
class RubricDraft:
    criteria: list[str] = field(default_factory=list)
    must_include: list[str] = field(default_factory=list)
    strong_signs: list[str] = field(default_factory=list)
    weak_signs: list[str] = field(default_factory=list)
    source_refs: list[str] = field(default_factory=list)


@dataclass
class GradeDraft:
    score: float = 0.0
    verdict: str = ""
    gaps: list[str] = field(default_factory=list)
    confidence_actual: float | None = None


def _strip_fences(text: str) -> str:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
    return cleaned.strip()


def _as_float(v, default: float | None) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def parse_rubric_json(text: str) -> RubricDraft:
    d = json.loads(_strip_fences(text))
    return RubricDraft(
        criteria=list(d.get("criteria", []) or []),
        must_include=list(d.get("must_include", []) or []),
        strong_signs=list(d.get("strong_signs", []) or []),
        weak_signs=list(d.get("weak_signs", []) or []),
        source_refs=list(d.get("source_refs", []) or []),
    )


def parse_grade_json(text: str) -> GradeDraft:
    d = json.loads(_strip_fences(text))
    return GradeDraft(
        score=_as_float(d.get("score"), 0.0) or 0.0,
        verdict=str(d.get("verdict", "")),
        gaps=list(d.get("gaps", []) or []),
        confidence_actual=_as_float(d.get("confidence_actual"), None),
    )
