# tests/test_assess_pure.py
from adaptive_academy.engine.assess import (
    apply_rules_checks, compute_delta, level_from_score, penalize_score,
)


def test_level_from_score_boundaries():
    assert level_from_score(0.9) == ("high", 0.9)
    assert level_from_score(0.75)[0] == "high"
    assert level_from_score(0.6)[0] == "medium"
    assert level_from_score(0.45)[0] == "medium"
    assert level_from_score(0.2)[0] == "low"
    assert level_from_score(1.5) == ("high", 1.0)  # clamped


def test_compute_delta():
    assert compute_delta(0.8, 0.6) == 0.2
    assert compute_delta(0.8, None) is None


def test_apply_rules_checks_flags_omissions_and_misconceptions():
    gaps = apply_rules_checks(
        response="attention uses softmax over scores",
        must_include=["softmax", "QK^T", "scale by sqrt(d)"],
        weak_signs=["it just picks the max"])
    assert any("QK^T" in g and "omitted" in g for g in gaps)
    assert any("scale by sqrt(d)" in g for g in gaps)
    assert not any("softmax" in g for g in gaps)  # present -> no gap


def test_penalize_score_floors_for_omissions():
    gaps = ["omitted required element: a", "omitted required element: b",
            "contains likely misconception: c"]
    # 0.9 - 2*0.15 = 0.6 (misconception does not subtract here)
    assert penalize_score(0.9, gaps) == 0.6
    assert penalize_score(0.1, ["omitted required element: a"]) == 0.0  # floored
