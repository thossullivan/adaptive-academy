"""The grading eval's scoring (evals/grading/metrics.py), on hand-built results.

No model and no case file: each test builds the few cases it needs, so a number here can be
checked by hand.
"""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.grading import metrics as m  # noqa: E402
from evals.grading.case_file import Case, Truth  # noqa: E402

REQ = ("a", "b")
MIS = ("m1", "m2")


def _case(cid, band, *, missing=(), committed=(), also=(), required=REQ,
          misconceptions=MIS) -> Case:
    return Case(
        id=cid, concept="c", kind="self_explanation", category="partial",
        criteria=("crit",), required=tuple(required), misconceptions=tuple(misconceptions),
        reference="", question="", answer="x",
        truth=Truth(band=band, also_acceptable=tuple(also), missing_required=tuple(missing),
                    misconceptions_committed=tuple(committed), rationale="r"),
        unsure="")


def _pred(cid, score, *, missing=(), committed=(), outcome="graded", cost=None,
          latency=None, calls=1, unpriced=0) -> m.Prediction:
    return m.Prediction(case_id=cid, outcome=outcome, final_score=score,
                        missing_required=tuple(missing),
                        misconceptions_committed=tuple(committed), cost_usd=cost,
                        latency_s=latency, calls=calls, unpriced_calls=unpriced)


# ── bands and ceilings ───────────────────────────────────────────────────────

def test_band_thresholds_match_the_apps_level_mapping():
    # band_of is the eval's copy of assess.level_from_score's thresholds; pinned together.
    from adaptive_academy.engine.assess import level_from_score

    for s in (0.0, 0.1, 0.3, 0.44, 0.45, 0.5, 0.7, 0.74, 0.75, 0.9, 1.0):
        assert m.band_of(s) == level_from_score(s)[0], s


def test_ceilings_match_the_apps_caps():
    from adaptive_academy.engine import output_checks as oc

    assert m.OMISSION_CEIL == oc.OMISSION_CEIL
    assert m.MISCONCEPTION_CEIL == oc.MISCONCEPTION_CEIL


def test_truth_ceiling_is_the_highest_score_the_truth_allows():
    assert m.truth_ceiling(_case("x", "high").truth) == 0.9
    assert m.truth_ceiling(_case("x", "medium").truth) == 0.7
    assert m.truth_ceiling(_case("x", "low").truth) == 0.3
    assert m.truth_ceiling(_case("x", "low", also=("medium",)).truth) == 0.7
    assert m.truth_ceiling(_case("x", "medium", missing=("a",)).truth) == 0.7
    assert m.truth_ceiling(_case("x", "medium", committed=("m1",)).truth) == 0.5


# ── the costly errors ────────────────────────────────────────────────────────

def test_false_mastery_needs_a_score_at_or_above_070_and_above_the_truth_ceiling():
    low = _case("low", "low", missing=("a", "b"))
    assert m.is_false_mastery(low, _pred("low", 0.7))  # weak answer recorded at 0.70
    assert m.is_false_mastery(low, _pred("low", 0.9))
    assert not m.is_false_mastery(low, _pred("low", 0.5))  # over-graded, not mastery
    medium = _case("med", "medium", missing=("a",))
    assert not m.is_false_mastery(medium, _pred("med", 0.7))  # the cap held
    assert m.is_false_mastery(medium, _pred("med", 0.9))
    wrong = _case("mis", "medium", committed=("m1",), also=("low",))
    assert m.is_false_mastery(wrong, _pred("mis", 0.7))  # misconception missed, not capped
    assert not m.is_false_mastery(wrong, _pred("mis", 0.5))
    high = _case("hi", "high")
    assert not m.is_false_mastery(high, _pred("hi", 0.9))
    assert not m.is_false_mastery(low, _pred("low", None, outcome="invalid_output"))


def test_false_cap_names_items_the_truth_says_are_covered_or_not_committed():
    case = _case("p", "medium", missing=("a",))
    assert m.false_cap_items(case, _pred("p", 0.7, missing=("a",))) == []
    assert m.false_cap_items(case, _pred("p", 0.5, missing=("a", "b"))) == ["b"]
    assert m.false_cap_items(case, _pred("p", 0.5, committed=("m2",))) == ["m2"]
    # A false cap counts even when the score was already under the ceiling: the learner's
    # record still says they missed something they covered.
    assert m.false_cap_items(case, _pred("p", 0.3, missing=("b",))) == ["b"]


def test_score_counts_the_costly_errors_with_case_ids_and_unanswered():
    cases = [
        _case("hi-ok", "high"),
        _case("hi-capped", "high"),
        _case("weak", "low", missing=("a", "b")),
        _case("weak-silent", "low", missing=("a", "b")),
        _case("mis", "medium", committed=("m1",), also=("low",)),
    ]
    preds = [
        _pred("hi-ok", 0.9),
        _pred("hi-capped", 0.5, committed=("m2",)),
        _pred("weak", 0.7, missing=("a",)),
        _pred("weak-silent", None, outcome="invalid_output", calls=2),
        _pred("mis", 0.5, committed=("m1",)),
    ]
    r = m.score(cases, preds)
    fm = r["false_mastery"]
    assert fm["case_ids"] == ["weak"]
    assert (fm["count"], fm["population"], fm["unanswered"], fm["denominator"]) == (1, 3, 1, 2)
    assert fm["rate"] == pytest.approx(0.5)
    fc = r["false_cap"]
    assert fc["case_ids"] == ["hi-capped"]
    assert fc["items"] == {"hi-capped": ["m2"]}
    assert fc["on_correct_answers"]["case_ids"] == ["hi-capped"]
    assert fc["on_correct_answers"]["denominator"] == 2
    assert r["invalid_output"] == {"count": 1, "denominator": 5, "rate": pytest.approx(0.2)}
    assert r["outcomes"] == {"graded": 4, "invalid_output": 1, "error": 0, "not_run": 0}


def test_band_accuracy_uses_acceptable_bands_and_the_confusion_table_the_primary_one():
    cases = [_case("a", "high"), _case("b", "medium", also=("low",)), _case("c", "low")]
    preds = [_pred("a", 0.7), _pred("b", 0.3), _pred("c", 0.1)]
    r = m.score(cases, preds)
    assert r["band_accuracy"]["correct"] == 2
    assert r["band_accuracy"]["rate"] == pytest.approx(2 / 3)
    assert r["confusion"]["high"]["medium"] == 1
    assert r["confusion"]["medium"]["low"] == 1
    assert r["confusion"]["low"]["low"] == 1


def test_item_precision_and_recall_are_micro_averaged_over_graded_cases():
    cases = [_case("x", "medium", missing=("a", "b"), committed=("m1",)),
             _case("y", "high")]
    preds = [_pred("x", 0.5, missing=("a",), committed=("m1", "m2")),
             _pred("y", 0.7, missing=("b",))]
    r = m.score(cases, preds)
    req = r["required_elements"]
    assert (req["tp"], req["fp"], req["fn"]) == (1, 1, 1)
    assert req["precision"] == pytest.approx(0.5)
    assert req["recall"] == pytest.approx(0.5)
    mis = r["misconceptions"]
    assert (mis["tp"], mis["fp"], mis["fn"]) == (1, 1, 0)
    assert mis["recall"] == pytest.approx(1.0)


def test_empty_denominators_read_as_none_not_zero():
    r = m.score([_case("hi", "high")], [_pred("hi", 0.9)])
    assert r["false_mastery"]["rate"] is None
    assert r["misconceptions"]["recall"] is None  # nothing was committed


def test_cost_and_latency_are_summed_and_unpriced_calls_named():
    cases = [_case("a", "high"), _case("b", "high"), _case("c", "high")]
    preds = [_pred("a", 0.9, cost=0.01, latency=2.0), _pred("b", 0.9, cost=0.03, latency=4.0),
             _pred("c", 0.9, cost=None, latency=6.0, unpriced=1)]
    r = m.score(cases, preds)
    assert r["cost"]["total_usd"] == pytest.approx(0.04)
    assert r["cost"]["priced_cases"] == 2
    assert r["cost"]["unpriced_calls"] == 1
    assert r["cost"]["mean_per_priced_case_usd"] == pytest.approx(0.02)
    assert r["latency"] == {"mean_s": pytest.approx(4.0), "p50_s": 4.0, "max_s": 6.0}


def test_score_refuses_predictions_for_unknown_or_missing_cases():
    with pytest.raises(ValueError):
        m.score([_case("a", "high")], [_pred("b", 0.9)])
    with pytest.raises(ValueError):
        m.score([_case("a", "high"), _case("b", "high")], [_pred("a", 0.9)])


# ── baselines ────────────────────────────────────────────────────────────────

def test_baselines_are_computed_from_the_cases_without_a_model():
    cases = [_case("hi", "high"), _case("weak", "low", missing=("a", "b")),
             _case("part", "medium", missing=("a",))]
    by_name = {name: m.score(cases, m.baseline_predictions(cases, name))
               for name in m.BASELINES}
    high = by_name["always_high_no_caps"]
    assert high["false_mastery"]["case_ids"] == ["weak", "part"]
    assert high["false_cap"]["count"] == 0
    assert by_name["always_medium"]["false_mastery"]["count"] == 0
    assert by_name["always_low"]["false_mastery"]["count"] == 0
    cap = by_name["cap_everything"]
    assert cap["false_cap"]["case_ids"] == ["hi", "weak", "part"]  # m1/m2 never committed
    assert cap["required_elements"]["recall"] == pytest.approx(1.0)
    assert cap["false_mastery"]["count"] == 0


def test_cap_everything_applies_the_same_ceilings_as_the_app():
    only_required = _case("r", "high", misconceptions=())
    (pred,) = m.baseline_predictions([only_required], "cap_everything")
    assert pred.final_score == 0.7
    (pred,) = m.baseline_predictions([_case("x", "high")], "cap_everything")
    assert pred.final_score == 0.5


def test_unknown_baseline_is_refused():
    with pytest.raises(KeyError):
        m.baseline_predictions([_case("x", "high")], "always_right")


def test_summary_table_puts_the_model_next_to_every_baseline():
    cases = [_case("hi", "high"), _case("weak", "low", missing=("a", "b"))]
    model = m.score(cases, [_pred("hi", 0.9), _pred("weak", 0.3, missing=("a", "b"))])
    table = m.summary_table("my-model", model, {
        name: m.score(cases, m.baseline_predictions(cases, name)) for name in m.BASELINES})
    lines = table.splitlines()
    assert lines[0].split()[0] == "row"
    assert any(line.startswith("my-model") for line in lines)
    for name in m.BASELINES:
        assert any(line.startswith(name) for line in lines)
    assert "0/1" in table  # the model's false mastery: 0 of 1 answered
