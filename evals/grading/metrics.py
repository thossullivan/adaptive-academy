"""Scoring for the grading eval. Pure: no app import, no model, no I/O.

A Prediction is what the app recorded for one case: the final score after the app's own caps
(assess.final_score) and the rubric items the grader named. score() compares predictions with
the case file's truth. The two costly errors come first:

  false mastery  the recorded score is 0.70 or more AND above the highest score the truth
                 allows (truth_ceiling). A weak or wrong answer recorded at 0.70+ tells the
                 learner they know something they don't. A cap that brings the score under
                 0.70 saves the case; a cap at exactly 0.70 does not.
  false cap      the grader named a required element the answer covers, or a misconception it
                 does not commit (per the truth). Each named item becomes an enforced gap and
                 a 0.70 / 0.50 ceiling in the app, so the learner's record says they missed
                 something they did not. Counted even when the score was already lower.

The constants below copy the app's thresholds; tests pin them to assess.level_from_score and
output_checks, so the eval cannot drift from the app without a failing test.
"""

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from statistics import mean, median

from evals.grading.case_file import BANDS, Case, Truth

# assess.level_from_score: >= 0.75 high, >= 0.45 medium, else low.
SCORE_HIGH = 0.75
SCORE_MEDIUM = 0.45
# output_checks.OMISSION_CEIL / MISCONCEPTION_CEIL (assess.penalize_score).
OMISSION_CEIL = 0.70
MISCONCEPTION_CEIL = 0.50
# A recorded score at or above this reads as mastery to the learner.
MASTERY_SCORE = 0.70
# The highest band midpoint inside each band (GRADE's midpoints: 0.1 0.3 | 0.5 0.7 | 0.9).
BAND_TOP = {"low": 0.3, "medium": 0.7, "high": 0.9}
_EPS = 1e-9

OUTCOMES = ("graded", "invalid_output", "error", "not_run")


@dataclass(frozen=True)
class Prediction:
    case_id: str
    # graded: a checked grade was recorded. invalid_output: the grade failed its output
    # checks twice, or the model refused or was cut off (the app records nothing).
    # error: any other failure (network, auth). not_run: the run stopped first (budget).
    outcome: str
    final_score: float | None = None
    missing_required: tuple[str, ...] = ()
    misconceptions_committed: tuple[str, ...] = ()
    cost_usd: float | None = None
    latency_s: float | None = None
    calls: int = 0
    unpriced_calls: int = 0


def band_of(score: float) -> str:
    s = max(0.0, min(1.0, score))
    return "high" if s >= SCORE_HIGH else "medium" if s >= SCORE_MEDIUM else "low"


def truth_ceiling(truth: Truth) -> float:
    """The highest score the truth allows: the top of the highest acceptable band, under the
    app's own ceilings for the items the truth says are missing or committed."""
    ceiling = max(BAND_TOP[b] for b in truth.acceptable_bands)
    if truth.missing_required:
        ceiling = min(ceiling, OMISSION_CEIL)
    if truth.misconceptions_committed:
        ceiling = min(ceiling, MISCONCEPTION_CEIL)
    return ceiling


def _graded(pred: Prediction) -> bool:
    return pred.outcome == "graded" and pred.final_score is not None


def is_false_mastery(case: Case, pred: Prediction) -> bool:
    if not _graded(pred):
        return False
    s = pred.final_score
    return s >= MASTERY_SCORE - _EPS and s > truth_ceiling(case.truth) + _EPS


def false_cap_items(case: Case, pred: Prediction) -> list[str]:
    """The items the grader named that the truth says the answer covers / does not commit."""
    if not _graded(pred):
        return []
    t = case.truth
    return ([i for i in pred.missing_required if i not in t.missing_required]
            + [i for i in pred.misconceptions_committed if i not in t.misconceptions_committed])


def _could_false_mastery(case: Case) -> bool:
    return truth_ceiling(case.truth) < BAND_TOP["high"] - _EPS


def _could_false_cap(case: Case) -> bool:
    t = case.truth
    return (any(i not in t.missing_required for i in case.required)
            or any(i not in t.misconceptions_committed for i in case.misconceptions))


def _rate(num: int, den: int) -> float | None:
    return num / den if den else None


def _costly(cases: Sequence[Case], preds: dict[str, Prediction], population, hit) -> dict:
    pop = [c for c in cases if population(c)]
    answered = [c for c in pop if _graded(preds[c.id])]
    ids = [c.id for c in answered if hit(c, preds[c.id])]
    return {"count": len(ids), "denominator": len(answered), "rate": _rate(len(ids), len(answered)),
            "population": len(pop), "unanswered": len(pop) - len(answered), "case_ids": ids}


def _pr(pairs: Iterable[tuple[Sequence[str], Sequence[str]]]) -> dict:
    tp = fp = fn = 0
    for predicted, truth in pairs:
        p, t = set(predicted), set(truth)
        tp, fp, fn = tp + len(p & t), fp + len(p - t), fn + len(t - p)
    return {"tp": tp, "fp": fp, "fn": fn,
            "precision": _rate(tp, tp + fp), "recall": _rate(tp, tp + fn)}


def score(cases: Sequence[Case], predictions: Sequence[Prediction]) -> dict:
    """Every metric for one row (a model or a baseline). One prediction per case."""
    preds = {p.case_id: p for p in predictions}
    ids = {c.id for c in cases}
    if set(preds) != ids or len(predictions) != len(cases):
        raise ValueError("predictions must name each case exactly once: "
                         f"unknown {sorted(set(preds) - ids)}, missing {sorted(ids - set(preds))}")
    outcomes = {o: sum(1 for p in predictions if p.outcome == o) for o in OUTCOMES}
    graded = [c for c in cases if _graded(preds[c.id])]

    false_mastery = _costly(cases, preds, _could_false_mastery, is_false_mastery)
    false_cap = _costly(cases, preds, _could_false_cap,
                        lambda c, p: bool(false_cap_items(c, p)))
    false_cap["items"] = {cid: false_cap_items(next(c for c in cases if c.id == cid), preds[cid])
                          for cid in false_cap["case_ids"]}
    correct = _costly(cases, preds, lambda c: c.truth.band == "high",
                      lambda c, p: bool(false_cap_items(c, p)))
    false_cap["on_correct_answers"] = {k: correct[k] for k in
                                       ("count", "denominator", "rate", "case_ids")}

    confusion = {t: {p: 0 for p in BANDS} for t in BANDS}
    hits = 0
    for c in graded:
        band = band_of(preds[c.id].final_score)
        confusion[c.truth.band][band] += 1
        hits += band in c.truth.acceptable_bands

    attempted = outcomes["graded"] + outcomes["invalid_output"]
    costs = [p.cost_usd for p in predictions if p.cost_usd is not None]
    latencies = [p.latency_s for p in predictions if p.latency_s is not None]
    return {
        "n_cases": len(cases),
        "outcomes": outcomes,
        "false_mastery": false_mastery,
        "false_cap": false_cap,
        "band_accuracy": {"correct": hits, "denominator": len(graded),
                          "rate": _rate(hits, len(graded))},
        "confusion": confusion,
        "required_elements": _pr((preds[c.id].missing_required, c.truth.missing_required)
                                 for c in graded),
        "misconceptions": _pr((preds[c.id].misconceptions_committed,
                               c.truth.misconceptions_committed) for c in graded),
        "invalid_output": {"count": outcomes["invalid_output"], "denominator": attempted,
                           "rate": _rate(outcomes["invalid_output"], attempted)},
        "cost": {"total_usd": sum(costs), "priced_cases": len(costs),
                 "calls": sum(p.calls for p in predictions),
                 "unpriced_calls": sum(p.unpriced_calls for p in predictions),
                 "mean_per_priced_case_usd": mean(costs) if costs else None},
        "latency": ({"mean_s": mean(latencies), "p50_s": median(latencies),
                     "max_s": max(latencies)} if latencies else None),
    }


# ── Baselines: rows that use no model ────────────────────────────────────────

BASELINES = ("always_high_no_caps", "always_medium", "always_low", "cap_everything")
BASELINE_NOTES = {
    "always_high_no_caps": "every answer recorded at 0.9, nothing named",
    "always_medium": "every answer recorded at 0.5, nothing named",
    "always_low": "every answer recorded at 0.1, nothing named",
    "cap_everything": "every required element named missing and every misconception "
                      "committed, under the app's ceilings",
}


def baseline_predictions(cases: Sequence[Case], name: str) -> list[Prediction]:
    if name not in BASELINES:
        raise KeyError(name)
    out = []
    for c in cases:
        if name == "cap_everything":
            s = 0.9
            if c.required:
                s = min(s, OMISSION_CEIL)
            if c.misconceptions:
                s = min(s, MISCONCEPTION_CEIL)
            out.append(Prediction(c.id, "graded", s, tuple(c.required),
                                  tuple(c.misconceptions)))
        else:
            s = {"always_high_no_caps": 0.9, "always_medium": 0.5, "always_low": 0.1}[name]
            out.append(Prediction(c.id, "graded", s))
    return out


# ── The text table printed after a run ───────────────────────────────────────

def _frac(cell: dict) -> str:
    rate = cell.get("rate")
    pct = "n/a" if rate is None else f"{rate:.0%}"
    text = f"{cell['count']}/{cell['denominator']} {pct}"
    if cell.get("unanswered"):
        text += f" ({cell['unanswered']} unanswered)"
    return text


def _pct(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.0%}"


def summary_table(model: str, result: dict, baselines: dict[str, dict]) -> str:
    """The model's row and every baseline's, in the same columns."""
    header = ("row", "false mastery", "false cap", "band acc", "req P/R", "misc P/R",
              "invalid")
    rows = [header]
    for name, r in [(model, result), *baselines.items()]:
        rows.append((
            name,
            _frac(r["false_mastery"]),
            _frac(r["false_cap"]),
            _pct(r["band_accuracy"]["rate"]),
            f"{_pct(r['required_elements']['precision'])}/"
            f"{_pct(r['required_elements']['recall'])}",
            f"{_pct(r['misconceptions']['precision'])}/{_pct(r['misconceptions']['recall'])}",
            _pct(r["invalid_output"]["rate"]),
        ))
    widths = [max(len(row[i]) for row in rows) for i in range(len(header))]
    return "\n".join("  ".join(cell.ljust(w) for cell, w in zip(row, widths)).rstrip()
                     for row in rows)
