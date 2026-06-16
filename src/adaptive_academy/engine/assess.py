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
