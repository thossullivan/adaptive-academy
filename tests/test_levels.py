from adaptive_academy.engine.levels import Levels, compute_levels
from adaptive_academy.models import KnowledgeEstimate


def _est(level: str) -> KnowledgeEstimate:
    return KnowledgeEstimate(concept_id=1, level=level)


def test_expert_gets_low_assistance_high_challenge():
    assert compute_levels(_est("high")) == Levels(assistance="low", challenge="high")


def test_novice_gets_high_assistance_low_challenge():
    assert compute_levels(_est("low")) == Levels(assistance="high", challenge="low")


def test_medium_is_balanced():
    assert compute_levels(_est("medium")) == Levels(assistance="medium", challenge="medium")


def test_missing_estimate_defaults_to_expert_lean():
    # No estimate yet -> default to low assistance (do no harm to an expert).
    assert compute_levels(None) == Levels(assistance="low", challenge="high")
