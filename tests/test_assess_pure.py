# tests/test_assess_pure.py
from adaptive_academy.engine.assess import (
    GradeDraft, compute_delta, level_from_score, penalize_score, rubric_gaps,
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


def test_rubric_gaps_name_the_items_as_sent():
    # The grader names items (any case/spacing; output_checks G13/G14 reject unknown ones);
    # the enforced gaps carry each item exactly as it was sent, once.
    grade = GradeDraft(missing_required=[" Softmax ", "softmax", "QK^T"],
                       misconceptions_committed=["it just picks the MAX"])
    gaps = rubric_gaps(grade, ["softmax", "QK^T", "weighted sum of values"],
                       ["it just picks the max"])
    assert gaps == ["omitted required element: softmax", "omitted required element: QK^T",
                    "contains likely misconception: it just picks the max"]
    assert rubric_gaps(GradeDraft(), ["softmax"], ["x"]) == []


def test_penalize_score_applies_band_ceilings():
    # Ceilings, not subtractions: an omission caps at 0.70, and a present misconception
    # caps further at 0.50 (worst applicable ceiling wins).
    gaps = ["omitted required element: a", "omitted required element: b",
            "contains likely misconception: c"]
    assert penalize_score(0.9, gaps) == 0.5
    assert penalize_score(0.9, ["omitted required element: a"]) == 0.7  # omission only
    assert penalize_score(0.3, ["omitted required element: a"]) == 0.3  # already below ceiling
    assert penalize_score(0.9, []) == 0.9  # a clean explanation passes through untouched
