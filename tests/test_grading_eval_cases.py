"""The grading eval's frozen case file (evals/grading/cases.jsonl) and its schema checks.

The file is hand-written; these tests keep it honest: every case has every field, every truth
item is one of the items the case sends, ids are unique, and the set covers what the eval
claims to cover (several concepts, both probe kinds, every category, every band).
"""

import json
import sys
from collections import Counter
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.grading.case_file import (  # noqa: E402
    BANDS, CATEGORIES, CaseFileError, case_problems, load_cases, parse_cases,
)

CASES_FILE = ROOT / "evals" / "grading" / "cases.jsonl"


@pytest.fixture(scope="module")
def cases():
    return load_cases(CASES_FILE)


def _valid() -> dict:
    return {
        "id": "x-1", "concept": "c", "kind": "self_explanation", "category": "partial",
        "criteria": ["crit"], "required": ["a", "b"], "misconceptions": ["m"],
        "reference": "", "answer": "an answer",
        "truth": {"band": "medium", "also_acceptable": ["low"], "missing_required": ["b"],
                  "misconceptions_committed": [], "rationale": "why"},
    }


# ── the frozen file ──────────────────────────────────────────────────────────

def test_the_case_file_loads_and_has_40_to_60_cases(cases):
    assert 40 <= len(cases) <= 60


def test_every_raw_line_has_every_field():
    for line in CASES_FILE.read_text(encoding="utf-8").splitlines():
        d = json.loads(line)
        assert case_problems(d) == [], d.get("id")
        for key in ("band", "missing_required", "misconceptions_committed", "rationale"):
            assert key in d["truth"]


def test_ids_are_unique(cases):
    ids = [c.id for c in cases]
    assert len(ids) == len(set(ids))


def test_truth_items_are_subsets_of_the_items_sent(cases):
    for c in cases:
        assert set(c.truth.missing_required) <= set(c.required), c.id
        assert set(c.truth.misconceptions_committed) <= set(c.misconceptions), c.id


def test_the_set_covers_several_concepts_both_kinds_every_category_and_band(cases):
    concepts = Counter(c.concept for c in cases)
    assert 4 <= len(concepts) <= 6
    assert max(concepts.values()) <= len(cases) // 2  # not one topic
    kinds = Counter(c.kind for c in cases)
    assert kinds["self_explanation"] > kinds["source_quiz"] >= 3
    assert {c.category for c in cases} == set(CATEGORIES)
    assert {c.truth.band for c in cases} == set(BANDS)


def test_the_costly_errors_have_cases_to_be_measured_on(cases):
    # False mastery needs answers whose truth ceiling is below 0.9; false cap needs correct
    # answers, including ones that name a misconception only to reject it.
    assert sum(c.truth.band != "high" for c in cases) >= 20
    assert sum(c.truth.band == "high" for c in cases) >= 15
    rejecting = [c for c in cases if c.category == "correct_names_misconception"]
    assert len(rejecting) >= 4
    assert all(c.truth.band == "high" and not c.truth.misconceptions_committed
               for c in rejecting)


def test_source_quiz_cases_are_shaped_as_the_app_sends_them(cases):
    for c in [c for c in cases if c.kind == "source_quiz"]:
        assert c.criteria == c.required and not c.misconceptions, c.id
        assert c.reference.strip() and c.question.strip(), c.id


# ── the schema checks themselves ─────────────────────────────────────────────

def test_a_valid_case_passes():
    assert case_problems(_valid()) == []


@pytest.mark.parametrize("mutate, message", [
    (lambda d: d.pop("answer"), "missing fields"),
    (lambda d: d["truth"].pop("rationale"), "truth is missing"),
    (lambda d: d["truth"].update(missing_required=["c"]), "not sent"),
    (lambda d: d["truth"].update(misconceptions_committed=["other"]), "not sent"),
    (lambda d: d["truth"].update(band="great"), "truth.band"),
    (lambda d: d["truth"].update(band="low", also_acceptable=["high"]), "next to"),
    (lambda d: d["truth"].update(band="high", also_acceptable=["medium"]), "high truth band"),
    (lambda d: d.update(kind="calibration"), "kind"),
    (lambda d: d.update(category="other"), "category"),
    (lambda d: d.update(required=["a", "a"]), "duplicate"),
    (lambda d: d.update(required=[]), "at least one"),
    (lambda d: d.update(reference="ref"), "no reference"),
    (lambda d: d.update(kind="source_quiz", reference="r"), "criteria must equal"),
    (lambda d: d.update(id="Bad Id"), "id must be"),
])
def test_schema_problems_are_named(mutate, message):
    d = _valid()
    mutate(d)
    problems = case_problems(d)
    assert any(message in p for p in problems), problems


def test_duplicate_ids_and_bad_lines_fail_the_whole_file():
    line = json.dumps(_valid())
    with pytest.raises(CaseFileError, match="duplicate id x-1"):
        parse_cases(line + "\n" + line)
    with pytest.raises(CaseFileError, match="line 2: not JSON"):
        parse_cases(line + "\n{oops")
    with pytest.raises(CaseFileError, match="no cases"):
        parse_cases("\n")
