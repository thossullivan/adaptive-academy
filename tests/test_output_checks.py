"""Named output checks for grader answers (engine/output_checks.py): golden replay + tables.

Golden replay (tests/golden/grades/): hand-written grader outputs, replayed through their
rubric. A known-good answer must pass; a known-bad one must FAIL on EXACTLY the expected rule
ids (and WARN on exactly the expected ones), so a rule that drifts — fires too often, or stops
firing — shows up as a named diff. expected.json lists every file.
"""

import json
import math
import re
from pathlib import Path

import pytest

from adaptive_academy.engine import assess, output_checks as oc
from adaptive_academy.llm.errors import classify_llm_error, describe_llm_error
from adaptive_academy.prompts import GRADE_CORRECTION

GOLDEN = Path(__file__).parent / "golden" / "grades"
EXPECTED = json.loads((GOLDEN / "expected.json").read_text())


# ── Golden replay ────────────────────────────────────────────────────────────

def test_every_golden_file_is_listed_and_every_listed_file_exists():
    on_disk = {p.name for p in GOLDEN.iterdir() if p.name != "expected.json"}
    assert on_disk == set(EXPECTED)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_golden_grade_fails_on_exactly_the_expected_rules(name):
    spec = EXPECTED[name]
    rubric = oc.RUBRICS[spec["rubric"]]
    ctx = oc.CheckContext(rules_gaps=tuple(spec.get("rules_gaps", [])))
    data, report = oc.check_output(rubric, (GOLDEN / name).read_text(), ctx)
    assert list(report.failed_ids) == spec["fail"], report
    assert list(report.warned_ids) == spec["warn"], report
    assert report.passed is (not spec["fail"])
    if "J1" not in spec["fail"]:
        assert isinstance(data, dict)


def test_golden_set_covers_every_rule_and_rubric():
    fired = {rid for spec in EXPECTED.values() for rid in spec["fail"] + spec["warn"]}
    all_ids = {r.id for rubric in oc.RUBRICS.values() for r in rubric.rules}
    assert fired == all_ids
    assert {spec["rubric"] for spec in EXPECTED.values()} == set(oc.RUBRICS)
    for rubric in oc.RUBRICS.values():  # each rubric has a passing example
        assert any(s["rubric"] == rubric.name and not s["fail"] for s in EXPECTED.values())


# ── Rule tables ──────────────────────────────────────────────────────────────

_CTX = oc.CheckContext()
_OMIT = oc.CheckContext(rules_gaps=("omitted required element: softmax",))
_MISC = oc.CheckContext(rules_gaps=("contains likely misconception: attention is memory",))

RULE_TABLE = [
    # (rule, answer, ctx, fires)
    (oc.G1, {"score": 0.0}, _CTX, False),
    (oc.G1, {"score": 1}, _CTX, False),
    (oc.G1, {"score": 0.55}, _CTX, False),
    (oc.G1, {}, _CTX, True),
    (oc.G1, {"score": None}, _CTX, True),
    (oc.G1, {"score": 1.0001}, _CTX, True),
    (oc.G1, {"score": -0.01}, _CTX, True),
    (oc.G1, {"score": 7}, _CTX, True),
    (oc.G1, {"score": math.nan}, _CTX, True),
    (oc.G1, {"score": math.inf}, _CTX, True),
    (oc.G1, {"score": "0.7"}, _CTX, True),
    (oc.G1, {"score": True}, _CTX, True),
    (oc.G1, {"score": [0.7]}, _CTX, True),
    (oc.G2, {"verdict": "ok"}, _CTX, False),
    (oc.G2, {}, _CTX, True),
    (oc.G2, {"verdict": ""}, _CTX, True),
    (oc.G2, {"verdict": " \n"}, _CTX, True),
    (oc.G2, {"verdict": ["ok"]}, _CTX, True),
    (oc.G3, {}, _CTX, False),
    (oc.G3, {"gaps": None}, _CTX, False),
    (oc.G3, {"gaps": []}, _CTX, False),
    (oc.G3, {"gaps": ["a", "b"]}, _CTX, False),
    (oc.G3, {"gaps": "a"}, _CTX, True),
    (oc.G3, {"gaps": ["a", 3]}, _CTX, True),
    (oc.G3, {"gaps": {"a": 1}}, _CTX, True),
    (oc.G4, {}, _CTX, False),
    (oc.G4, {"confidence_actual": None}, _CTX, False),
    (oc.G4, {"confidence_actual": 0.4}, _CTX, False),
    (oc.G4, {"confidence_actual": 1.5}, _CTX, True),
    (oc.G4, {"confidence_actual": "high"}, _CTX, True),
    (oc.G4, {"confidence_actual": math.nan}, _CTX, True),
    (oc.G5, {}, _CTX, False),
    (oc.G5, {"mechanism_present": False}, _CTX, False),
    (oc.G5, {"mechanism_present": True}, _CTX, False),
    (oc.G5, {"mechanism_present": "false"}, _CTX, True),
    (oc.G5, {"mechanism_present": 0}, _CTX, True),
    (oc.G5, {"mechanism_present": None}, _CTX, True),
    (oc.G6, {"mechanism_present": False}, _CTX, False),
    (oc.G6, {}, _CTX, True),
    (oc.G7, {"score": 0.5, "mechanism_present": False}, _CTX, False),
    (oc.G7, {"score": 0.9, "mechanism_present": True}, _CTX, False),
    (oc.G7, {"score": 0.9}, _CTX, False),
    (oc.G7, {"score": 0.7, "mechanism_present": False}, _CTX, True),
    (oc.G7, {"score": "bad", "mechanism_present": False}, _CTX, False),  # G1's job
    (oc.G8, {"score": 0.1}, _CTX, False),
    (oc.G8, {"score": 0.7}, _CTX, False),
    (oc.G8, {"score": 0.6}, _CTX, True),
    (oc.G8, {"score": 0.4}, _CTX, True),
    (oc.G8, {"score": 7}, _CTX, False),  # G1's job
    (oc.G9, {"score": 0.9}, _CTX, False),
    (oc.G9, {"score": 0.7}, _OMIT, False),
    (oc.G9, {"score": 0.9}, _OMIT, True),
    (oc.G9, {"score": 0.5}, _MISC, False),
    (oc.G9, {"score": 0.7}, _MISC, True),
    (oc.G10, {"score": 0.9, "gaps": []}, _CTX, False),
    (oc.G10, {"score": 0.5, "gaps": ["x"]}, _CTX, False),
    (oc.G10, {"score": 0.5, "gaps": []}, _CTX, True),
    (oc.G10, {"score": 0.5}, _CTX, True),
    (oc.G10, {"score": 0.5, "gaps": [" "]}, _CTX, True),
    (oc.F1, {"feedback": "clear"}, _CTX, False),
    (oc.F1, {}, _CTX, True),
    (oc.F1, {"feedback": ""}, _CTX, True),
    (oc.T1, {}, _CTX, False),
    (oc.T1, {"strengths": ["a"]}, _CTX, False),
    (oc.T1, {"strengths": "a"}, _CTX, True),
    (oc.P1, {"canonical": "do X"}, _CTX, False),
    (oc.P1, {"canonical": ""}, _CTX, True),
    (oc.P1, {}, _CTX, True),
    (oc.P2, {"score": 0.4}, _CTX, False),
    (oc.P2, {"score": 0.5}, _CTX, True),
    (oc.O1, {"result": "demo booked"}, _CTX, False),
    (oc.O1, {"result": 3}, _CTX, True),
    (oc.O2, {"summary": "s"}, _CTX, False),
    (oc.O2, {}, _CTX, True),
]


@pytest.mark.parametrize("rule,answer,ctx,fires", RULE_TABLE,
                         ids=[f"{r.id}-{i}" for i, (r, *_rest) in enumerate(RULE_TABLE)])
def test_rule_table(rule, answer, ctx, fires):
    message = rule.check(answer, ctx)
    assert (message is not None) is fires, message
    if fires:
        assert isinstance(message, str) and message


@pytest.mark.parametrize("text,ok", [
    ('{"a": 1}', True),
    ('Sure:\n```json\n{"a": 1}\n```', True),
    ("", False),
    ("not json", False),
    ("[1, 2]", False),
    ('"a string"', False),
    ('{"a": ', False),
])
def test_j1_parse_answer(text, ok):
    data, problem = oc.parse_answer(text)
    assert (data is not None) is ok
    assert (problem is None) is ok


def test_j1_failure_skips_the_other_rules():
    data, report = oc.check_output(oc.GRADE_RUBRIC, "nope")
    assert data is None and report.failed_ids == ("J1",) and not report.warnings


# ── Rubric shape ─────────────────────────────────────────────────────────────

def test_rule_ids_are_unique_and_documented():
    rules = {r.id: r for rubric in oc.RUBRICS.values() for r in rubric.rules}
    doc = oc.__doc__
    for rid, rule in rules.items():
        assert re.search(rf"^\s+{rid}\s+{rule.severity}\s", doc, re.M), \
            f"{rid} missing from the module docstring"
    for rubric in oc.RUBRICS.values():
        assert len(set(rubric.ids)) == len(rubric.ids)
        assert rubric.ids[0] == "J1"


def test_ceilings_match_assess():
    assert oc.OMISSION_CEIL == assess._OMISSION_CEIL
    assert oc.MISCONCEPTION_CEIL == assess._MISCONCEPTION_CEIL
    assert oc.NO_MECHANISM_CEIL == assess._NO_MECHANISM_CEIL
    gaps = assess.apply_rules_checks("no terms here", ["softmax"], ["here"])
    assert oc.rules_ceiling(gaps) == assess.penalize_score(1.0, gaps)


# ── Decision + correction ────────────────────────────────────────────────────

_PASS = oc.CheckReport("grade", (oc.RuleResult("G8", oc.WARN, "off band"),))
_FAILED = oc.CheckReport("grade", (oc.RuleResult("G1", oc.FAIL, "score is 7, outside [0, 1]"),
                                   oc.RuleResult("G8", oc.WARN, "off band")))


@pytest.mark.parametrize("report,attempt,action", [
    (_PASS, 1, oc.ACCEPT),
    (_PASS, 2, oc.ACCEPT),
    (_FAILED, 1, oc.REGENERATE),
    (_FAILED, 2, oc.REJECT),
    (_FAILED, 3, oc.REJECT),
])
def test_decide(report, attempt, action):
    assert oc.decide(report, attempt) == action


def test_warnings_never_block():
    assert _PASS.passed and _PASS.warned_ids == ("G8",) and _PASS.failed_ids == ()


def test_correction_message_names_failed_rules_only():
    text = oc.correction_message(_FAILED)
    assert "- G1: score is 7, outside [0, 1]" in text
    assert "G8" not in text  # a warning is not something to correct
    assert text.startswith(GRADE_CORRECTION.split("{failures}")[0])


def test_summarize():
    assert oc.summarize(_FAILED, 1) == "grade attempt=1 fail FAIL G1 WARN G8"
    assert oc.summarize(_PASS, 2) == "grade attempt=2 pass WARN G8"


def test_grade_check_error_is_invalid_output_502():
    exc = oc.GradeCheckError("grade", ("G1", "G3"))
    assert classify_llm_error(exc) == "invalid_output"
    failure = describe_llm_error(exc)
    assert failure.status_code == 502 and failure.category == "invalid_output"
    assert "G1, G3" in failure.detail and "nothing was recorded" in failure.detail
