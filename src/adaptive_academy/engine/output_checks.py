"""Named output checks for grader answers — pure functions, no session, no model.

Every grader returns free-text JSON. Before this module it was parsed leniently and written
straight into Assessment rows: `float(score)` took 7, -1 or NaN; `bool("false")` is True, so a
string mechanism flag silently disabled the illusion-of-competence cap; a gaps *string* became
a list of its characters. Here each grader's answer is checked against a rubric of NAMED rules
before anything is written (engine/grade_gate.py does the I/O: regenerate once on a FAIL,
reject if a FAIL survives, record every result as an AgentEvent).

A rule has a stable id, a severity, and a check that returns None (pass) or a short sentence
saying what was wrong. FAIL blocks the write; WARN is recorded in the trace and does not
block (used where code already enforces the property, so the grade is safe but the grader
contradicted itself or its prompt).

Rules, with the reason each exists:

  J1  FAIL  The answer parses to a JSON object. Every grader reads keys off a dict; prose,
            an array, or truncated JSON raised json.JSONDecodeError (or AttributeError).
  G1  FAIL  "score" is present and a finite JSON number in [0, 1] (not a string, not a
            boolean). It becomes Assessment.score and, for GRADING_KINDS, the
            KnowledgeEstimate level; assess.parse_grade_json took any float (7, -1, NaN)
            and defaulted a missing score to 0.0, a silent fake grade.
  G2  FAIL  "verdict" is a non-empty string. It is Assessment.verdict (and, for artifacts,
            Deliverable.review_verdict): the learner's only reason for the score.
  G3  FAIL  "gaps", when present, is a list of strings. It is Assessment.gaps; a string
            would be split into characters by list(). Absent reads as no gaps (see G10).
  G4  FAIL  "confidence_actual", when present and not null, is a finite number in [0, 1].
            assess_concept writes it to Assessment.confidence_actual for non-calibration
            kinds, which the calibration loop compares against predicted confidence.
  G5  FAIL  "mechanism_present", when present, is a JSON boolean. bool() of any non-empty
            string is True, so "false" would disable the code-enforced 0.50 cap.
  G6  WARN  "mechanism_present" is present. Absent defaults to True (assess.GradeDraft), so
            the cap cannot fire; GRADE and ASSESS_ARTIFACT both require the field.
  G7  WARN  mechanism_present=false implies score <= 0.50. The prompts state this HARD CAP;
            assess_concept and review_artifact enforce it in code, so a breach is recorded,
            not blocked.
  G8  WARN  "score" is a band midpoint (0.1, 0.3, 0.5, 0.7, 0.9). GRADE and ASSESS_ARTIFACT
            say "use the band MIDPOINT, do not invent other floats".
  G9  WARN  "score" does not exceed the ceiling the grader's own rubric fields imply (a
            missing_required entry caps at 0.70, a misconceptions_committed entry at 0.50;
            assess.penalize_score). assess_concept applies the ceiling in code anyway, so
            this records the grader contradicting itself without blocking it.
  G10 WARN  A score below the top band (< 0.9) names at least one gap (in gaps,
            missing_required or misconceptions_committed). Every band below 0.90 is defined
            by something missing; a low grade with no gaps tells the learner nothing to fix.
  G11 FAIL  "missing_required" is present and a list of strings. GRADE (v6) requires it:
            it is how the grader reports a REQUIRED ELEMENT the answer does not cover, and
            the code caps on it. Absent would read as "nothing missing", an uncapped grade.
  G12 FAIL  "misconceptions_committed" is present and a list of strings: the same, for a
            KNOWN MISCONCEPTION the answer commits (the 0.50 cap).
  G13 FAIL  Every missing_required entry is one of the REQUIRED ELEMENTS sent (compared
            trimmed and casefolded; CheckContext.required). The entry becomes the recorded
            gap "omitted required element: <item>"; an invented or paraphrased one would
            put words the rubric never had into the learner's record, so the regeneration
            names it.
  G14 FAIL  Every misconceptions_committed entry is one of the KNOWN MISCONCEPTIONS sent
            (CheckContext.misconceptions), for the same reason.
  F1  FAIL  "feedback" is a non-empty string. Teach-It and Productive Failure store it as
            Assessment.verdict (the learner's reason for the score).
  T1  FAIL  "strengths", when present, is a list of strings (returned by /teach; a string
            would be split into characters).
  P1  FAIL  "canonical" is a non-empty string. Consolidation is the instruction that must
            follow a productive-failure attempt; without it the step teaches nothing.
  P2  WARN  "score" is a PF_CONSOLIDATE band midpoint (0.1, 0.4, 0.7, 0.9).
  O1  FAIL  "result" is a non-empty string (roleplay / paper-probe debrief, shown as the
            outcome headline).
  O2  FAIL  "summary" is a non-empty string (the debrief body shown with it).

Not covered, on purpose: a "verdict claims mastery while the score is low" rule (the code has
no mastery vocabulary to check a verdict against, and keyword-matching prose would be vibes);
a multi-concept coverage rule (no grader returns several concepts in one answer: roleplay and
paper probe grade each concept with its own assess_concept call, so coverage is code, not
model output).
"""

import json
import math
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.types import StructuredOutputError
from adaptive_academy.prompts import GRADE_CORRECTION

FAIL = "FAIL"
WARN = "WARN"

# Score ceilings assess_concept enforces (kept equal to assess._OMISSION_CEIL /
# _MISCONCEPTION_CEIL / _NO_MECHANISM_CEIL; a test pins them together).
OMISSION_CEIL = 0.70
MISCONCEPTION_CEIL = 0.50
NO_MECHANISM_CEIL = 0.50
_OMISSION_PREFIX = "omitted required element"
_MISCONCEPTION_PREFIX = "contains likely misconception"

GRADE_BANDS = (0.1, 0.3, 0.5, 0.7, 0.9)
PF_BANDS = (0.1, 0.4, 0.7, 0.9)
_TOP_BAND = 0.9
_EPS = 1e-9


@dataclass(frozen=True)
class CheckContext:
    """Facts the checks need that are not in the answer itself."""

    # The rubric items sent to the grader (assess.build_grade_prompt): REQUIRED ELEMENTS
    # (must_include / source-quiz key points) and KNOWN MISCONCEPTIONS (weak_signs).
    required: tuple[str, ...] = ()
    misconceptions: tuple[str, ...] = ()


@dataclass(frozen=True)
class Rule:
    id: str
    severity: str  # FAIL or WARN
    description: str
    check: Callable[[dict[str, Any], CheckContext], str | None]


@dataclass(frozen=True)
class RuleResult:
    rule_id: str
    severity: str
    message: str


@dataclass(frozen=True)
class CheckReport:
    """The rules an answer broke (passing rules are not listed)."""

    rubric: str
    results: tuple[RuleResult, ...] = ()

    @property
    def failures(self) -> tuple[RuleResult, ...]:
        return tuple(r for r in self.results if r.severity == FAIL)

    @property
    def warnings(self) -> tuple[RuleResult, ...]:
        return tuple(r for r in self.results if r.severity == WARN)

    @property
    def failed_ids(self) -> tuple[str, ...]:
        return tuple(r.rule_id for r in self.failures)

    @property
    def warned_ids(self) -> tuple[str, ...]:
        return tuple(r.rule_id for r in self.warnings)

    @property
    def passed(self) -> bool:
        return not self.failures


@dataclass(frozen=True)
class Rubric:
    name: str
    rules: tuple[Rule, ...] = field(default_factory=tuple)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(r.id for r in self.rules)


class GradeCheckError(StructuredOutputError):
    """A grader's answer still failed a FAIL rule after one regeneration. Nothing was written.

    A StructuredOutputError, so llm/errors.py classifies it as `invalid_output` and the API
    answers 502 with that category (api/app.py)."""

    def __init__(self, rubric: str, rule_ids: tuple[str, ...]):
        self.rubric = rubric
        self.rule_ids = tuple(rule_ids)
        super().__init__(
            "failed_checks",
            f"{rubric} output failed checks {', '.join(self.rule_ids)} after one regeneration")

    @property
    def detail(self) -> str:
        return (f"The model's grade failed its output checks twice "
                f"({', '.join(self.rule_ids)}), so nothing was recorded and your learning "
                "record is unchanged. Try again. It usually works the second time.")


# ── Value helpers ────────────────────────────────────────────────────────────

def _is_number(v: Any) -> bool:
    # bool is an int subclass in Python, and JSON true is not a score.
    return isinstance(v, int | float) and not isinstance(v, bool)


def _unit_number_problem(name: str, v: Any) -> str | None:
    if not _is_number(v):
        return f"{name} is {json.dumps(v)}, not a number"
    try:
        finite = math.isfinite(v)
    except OverflowError:  # a JSON integer too large for a float (e.g. 400 digits)
        return f"{name} is an integer too large to be a score"
    if not finite:
        return f"{name} is {v}, not a finite number"
    if not 0.0 <= v <= 1.0:
        return f"{name} is {v}, outside [0, 1]"
    return None


def _non_empty_string(d: dict[str, Any], key: str) -> str | None:
    v = d.get(key)
    if v is None:
        return f"{key} is missing"
    if not isinstance(v, str):
        return f"{key} is {type(v).__name__}, not a string"
    if not v.strip():
        return f"{key} is empty"
    return None


def _string_list(d: dict[str, Any], key: str) -> str | None:
    if key not in d or d[key] is None:
        return None
    v = d[key]
    if not isinstance(v, list):
        return f"{key} is {type(v).__name__}, not a list of strings"
    bad = [x for x in v if not isinstance(x, str)]
    if bad:
        return f"{key} has non-string entries ({json.dumps(bad[0])})"
    return None


def _valid_score(d: dict[str, Any]) -> float | None:
    v = d.get("score")
    if _unit_number_problem("score", v) is None:
        return float(v)
    return None


def _on_band(score: float, bands: tuple[float, ...]) -> bool:
    return any(abs(score - b) < 1e-6 for b in bands)


def item_key(item: str) -> str:
    """How a named rubric item is compared with the items sent: trimmed, inner whitespace
    collapsed, casefolded."""
    return " ".join(item.split()).casefold()


def match_items(entries: list[str],
                items: tuple[str, ...] | list[str]) -> tuple[list[str], list[str]]:
    """The sent items the grader's entries name (each once, as given, in entry order), and
    the entries that name none of them."""
    by_key = {item_key(i): i for i in reversed(list(items))}  # first spelling wins
    found: list[str] = []
    unknown: list[str] = []
    for entry in entries:
        item = by_key.get(item_key(entry))
        if item is None:
            unknown.append(entry)
        elif item not in found:
            found.append(item)
    return found, unknown


def rules_ceiling(rules_gaps: tuple[str, ...] | list[str]) -> float:
    """The highest score the enforced rubric gaps allow (assess.penalize_score)."""
    ceiling = 1.0
    if any(g.startswith(_OMISSION_PREFIX) for g in rules_gaps):
        ceiling = min(ceiling, OMISSION_CEIL)
    if any(g.startswith(_MISCONCEPTION_PREFIX) for g in rules_gaps):
        ceiling = min(ceiling, MISCONCEPTION_CEIL)
    return ceiling


# ── Checks ───────────────────────────────────────────────────────────────────

def _g1(d, _ctx):
    if "score" not in d:
        return "score is missing"
    return _unit_number_problem("score", d["score"])


def _g2(d, _ctx):
    return _non_empty_string(d, "verdict")


def _g3(d, _ctx):
    return _string_list(d, "gaps")


def _g4(d, _ctx):
    v = d.get("confidence_actual")
    if v is None:
        return None
    return _unit_number_problem("confidence_actual", v)


def _g5(d, _ctx):
    if "mechanism_present" not in d:
        return None
    v = d["mechanism_present"]
    if not isinstance(v, bool):
        return f"mechanism_present is {json.dumps(v)}, not true or false"
    return None


def _g6(d, _ctx):
    if "mechanism_present" not in d:
        return "mechanism_present is missing (read as true, so the 0.50 cap cannot apply)"
    return None


def _g7(d, _ctx):
    score = _valid_score(d)
    if d.get("mechanism_present") is False and score is not None and score > NO_MECHANISM_CEIL:
        return f"score is {score} with mechanism_present=false (cap is {NO_MECHANISM_CEIL})"
    return None


def _band_check(bands: tuple[float, ...]):
    def check(d, _ctx):
        score = _valid_score(d)
        if score is not None and not _on_band(score, bands):
            return f"score {score} is not a band midpoint {list(bands)}"
        return None
    return check


_MISSING = "missing_required"
_COMMITTED = "misconceptions_committed"


def _named(d: dict[str, Any], key: str) -> list[str]:
    v = d.get(key)
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _g9(d, _ctx):
    score = _valid_score(d)
    ceiling = 1.0
    if _named(d, _MISSING):
        ceiling = min(ceiling, OMISSION_CEIL)
    if _named(d, _COMMITTED):
        ceiling = min(ceiling, MISCONCEPTION_CEIL)
    if score is not None and score > ceiling + _EPS:
        return (f"score {score} is above the {ceiling} ceiling its own {_MISSING} / "
                f"{_COMMITTED} imply")
    return None


def _g10(d, _ctx):
    score = _valid_score(d)
    gaps = d.get("gaps")
    if gaps and not isinstance(gaps, list):
        return None  # a malformed gaps value is G3's job
    named = [g for key in ("gaps", _MISSING, _COMMITTED) for g in _named(d, key) if g.strip()]
    if score is not None and score < _TOP_BAND - _EPS and not named:
        return f"score {score} is below the top band but no gaps are named"
    return None


def _required_string_list(key: str):
    def check(d, _ctx):
        if key not in d:
            return f"{key} is missing (use [] when there is nothing to list)"
        if d[key] is None:
            return f"{key} is null, not a list of strings"
        return _string_list(d, key)
    return check


def _only_sent_items(key: str, heading: str, sent: Callable[[CheckContext], tuple[str, ...]]):
    def check(d, ctx: CheckContext):
        _, unknown = match_items(_named(d, key), sent(ctx))
        if not unknown:
            return None
        allowed = "; ".join(sent(ctx)) or "none were listed"
        return (f"{key} names {json.dumps(unknown, ensure_ascii=False)}, not one of the "
                f"{heading} as given ({allowed})")
    return check


def _f1(d, _ctx):
    return _non_empty_string(d, "feedback")


def _t1(d, _ctx):
    return _string_list(d, "strengths")


def _p1(d, _ctx):
    return _non_empty_string(d, "canonical")


def _o1(d, _ctx):
    return _non_empty_string(d, "result")


def _o2(d, _ctx):
    return _non_empty_string(d, "summary")


J1 = Rule("J1", FAIL, "answer parses to a JSON object", lambda d, ctx: None)  # see check_output
G1 = Rule("G1", FAIL, "score is a finite number in [0, 1]", _g1)
G2 = Rule("G2", FAIL, "verdict is a non-empty string", _g2)
G3 = Rule("G3", FAIL, "gaps is a list of strings", _g3)
G4 = Rule("G4", FAIL, "confidence_actual is null or a finite number in [0, 1]", _g4)
G5 = Rule("G5", FAIL, "mechanism_present is a boolean", _g5)
G6 = Rule("G6", WARN, "mechanism_present is present", _g6)
G7 = Rule("G7", WARN, "no mechanism means score <= 0.50", _g7)
G8 = Rule("G8", WARN, "score is a grade band midpoint", _band_check(GRADE_BANDS))
G9 = Rule("G9", WARN, "score respects the ceiling its rubric fields imply", _g9)
G10 = Rule("G10", WARN, "a below-top-band score names a gap", _g10)
G11 = Rule("G11", FAIL, "missing_required is a list of strings",
           _required_string_list(_MISSING))
G12 = Rule("G12", FAIL, "misconceptions_committed is a list of strings",
           _required_string_list(_COMMITTED))
G13 = Rule("G13", FAIL, "missing_required names only REQUIRED ELEMENTS sent",
           _only_sent_items(_MISSING, "REQUIRED ELEMENTS", lambda ctx: ctx.required))
G14 = Rule("G14", FAIL, "misconceptions_committed names only KNOWN MISCONCEPTIONS sent",
           _only_sent_items(_COMMITTED, "KNOWN MISCONCEPTIONS", lambda ctx: ctx.misconceptions))
F1 = Rule("F1", FAIL, "feedback is a non-empty string", _f1)
T1 = Rule("T1", FAIL, "strengths is a list of strings", _t1)
P1 = Rule("P1", FAIL, "canonical is a non-empty string", _p1)
P2 = Rule("P2", WARN, "score is a productive-failure band midpoint", _band_check(PF_BANDS))
O1 = Rule("O1", FAIL, "result is a non-empty string", _o1)
O2 = Rule("O2", FAIL, "summary is a non-empty string", _o2)

# assess.grade (assess_concept, so also roleplay / paper-probe / decay per-concept grades)
GRADE_RUBRIC = Rubric(
    "grade", (J1, G1, G2, G3, G4, G5, G6, G7, G8, G9, G10, G11, G12, G13, G14))
# assess.artifact: same core answer shape, but ASSESS_ARTIFACT sends no rubric items and asks
# for no rubric fields, so G9 and G11-G14 don't apply.
ARTIFACT_RUBRIC = Rubric("artifact", (J1, G1, G2, G3, G4, G5, G6, G7, G8, G10))
TEACH_RUBRIC = Rubric("teach", (J1, G1, F1, T1, G3))
CONSOLIDATE_RUBRIC = Rubric("consolidate", (J1, G1, F1, P1, P2))
OUTCOME_RUBRIC = Rubric("outcome", (J1, O1, O2))

RUBRICS = {r.name: r for r in (GRADE_RUBRIC, ARTIFACT_RUBRIC, TEACH_RUBRIC,
                               CONSOLIDATE_RUBRIC, OUTCOME_RUBRIC)}


def parse_answer(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """The answer as a dict, or None and what was wrong (rule J1)."""
    try:
        data = json.loads(extract_json(text or ""))
    except (json.JSONDecodeError, ValueError) as exc:
        return None, f"not valid JSON ({exc.__class__.__name__}: {str(exc)[:80]})"
    if not isinstance(data, dict):
        return None, f"a JSON {type(data).__name__}, not an object"
    return data, None


def check_output(rubric: Rubric, text: str,
                 ctx: CheckContext | None = None) -> tuple[dict[str, Any] | None, CheckReport]:
    """Parse and check one answer. Returns (data or None, report). If J1 fails the other
    rules are not run: they read keys off an object that does not exist."""
    ctx = ctx or CheckContext()
    data, problem = parse_answer(text)
    if data is None:
        return None, CheckReport(rubric.name, (RuleResult("J1", FAIL, problem or "unparseable"),))
    results = []
    for rule in rubric.rules:
        if rule.id == "J1":
            continue
        message = rule.check(data, ctx)
        if message is not None:
            results.append(RuleResult(rule.id, rule.severity, message))
    return data, CheckReport(rubric.name, tuple(results))


# ── Decision (kew-style: pure, separate from I/O) ───────────────────────────

ACCEPT = "accept"
REGENERATE = "regenerate"
REJECT = "reject"
MAX_ATTEMPTS = 2  # the first answer plus one regeneration


def decide(report: CheckReport, attempt: int) -> str:
    """What to do with a checked answer on this (1-based) attempt."""
    if report.passed:
        return ACCEPT
    return REGENERATE if attempt < MAX_ATTEMPTS else REJECT


def correction_message(report: CheckReport) -> str:
    """The append-only correction turn: the failed rule ids and what was wrong."""
    lines = "\n".join(f"- {r.rule_id}: {r.message}" for r in report.failures)
    return GRADE_CORRECTION.format(failures=lines)


def summarize(report: CheckReport, attempt: int) -> str:
    """One-line AgentEvent detail for a check."""
    parts = [f"{report.rubric} attempt={attempt}", "pass" if report.passed else "fail"]
    if report.failures:
        parts.append("FAIL " + ",".join(report.failed_ids))
    if report.warnings:
        parts.append("WARN " + ",".join(report.warned_ids))
    return " ".join(parts)
