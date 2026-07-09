from datetime import datetime, timedelta

from adaptive_academy.engine.gates import evaluate_concept
from adaptive_academy.models import Assessment

T0 = datetime(2026, 7, 1, 12, 0, 0)


def _a(id: int, kind: str, score: float, days_after_t0: float) -> Assessment:
    return Assessment(id=id, concept_id=1, kind=kind, prompt="p", score=score,
                      created_at=T0 + timedelta(days=days_after_t0))


def test_no_assessments_is_never_probed_cold():
    ev = evaluate_concept(1, "attention", [])
    assert ev.verdict == "never_probed_cold"
    assert not ev.delayed_ok and not ev.artifact_ok


def test_recall_too_soon_does_not_count_as_delayed():
    rows = [_a(1, "self_explanation", 0.8, 0),
            _a(2, "recall", 0.8, 3)]  # only 3 days later
    assert evaluate_concept(1, "attention", rows).verdict == "never_probed_cold"


def test_delayed_held_recall_but_no_artifact_is_weak_artifact():
    rows = [_a(1, "self_explanation", 0.8, 0),
            _a(2, "recall", 0.75, 8)]  # 8d later, 0.75 >= 0.8*0.85
    ev = evaluate_concept(1, "attention", rows)
    assert ev.delayed_ok and not ev.artifact_ok
    assert ev.verdict == "weak_artifact"


def test_delayed_decayed_recall_is_stale():
    rows = [_a(1, "self_explanation", 0.9, 0),
            _a(2, "recall", 0.5, 8)]  # 0.5 < 0.9*0.85
    assert evaluate_concept(1, "attention", rows).verdict == "stale"


def test_latest_delayed_recall_wins_over_earlier_held():
    rows = [_a(1, "teach", 0.9, 0),
            _a(2, "recall", 0.9, 8),    # held
            _a(3, "self_explanation", 0.9, 9),
            _a(4, "recall", 0.3, 20)]   # latest delayed recall decayed
    assert evaluate_concept(1, "attention", rows).verdict == "stale"


def test_verified_needs_delayed_held_plus_artifact_at_threshold():
    rows = [_a(1, "teach", 0.7, 0),          # artifact at threshold counts
            _a(2, "recall", 0.65, 8)]        # 0.65 >= 0.7*0.85 = 0.595
    ev = evaluate_concept(1, "attention", rows)
    assert ev.delayed_ok and ev.artifact_ok
    assert ev.verdict == "verified"


def test_weak_artifact_score_below_threshold():
    rows = [_a(1, "productive_failure", 0.69, 0),
            _a(2, "recall", 0.69, 8)]
    assert evaluate_concept(1, "attention", rows).verdict == "weak_artifact"


def test_recall_with_no_prior_non_recall_is_ignored():
    rows = [_a(1, "recall", 0.9, 0)]  # nothing to be "delayed" relative to
    assert evaluate_concept(1, "attention", rows).verdict == "never_probed_cold"
