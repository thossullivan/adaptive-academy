"""The frozen case file: loading and validating it. Pure: no app import, no model.

One JSON object per line of cases.jsonl. What the grader is shown is only what the app would
send for a real learner (assess.grade_request): concept, kind, criteria, required elements,
known misconceptions, the reference answer (source quiz only) and the learner's answer.
Everything else in a case (id, category, question, truth, unsure) is for scoring and for
people, and never reaches the prompt (tests/test_grading_eval_runner.py checks that).
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

BANDS = ("low", "medium", "high")
KINDS = ("self_explanation", "source_quiz")
CATEGORIES = (
    "correct",                    # a full, correct answer in plain words
    "correct_other_notation",     # correct, in other notation, wording, spelling or convention
    "correct_names_misconception",  # correct, and names a known misconception to reject it
    "fluent_missing_key_idea",    # reads well, but leaves out a required element
    "commits_misconception",      # asserts a known misconception
    "partial",                    # some required elements, not all
    "wrong_confident",            # wrong, stated with confidence
    "off_topic",                  # about something else
    "very_short",                 # a line or less
    "injection",                  # tries to instruct the grader
)
_ID = re.compile(r"[a-z0-9]+(-[a-z0-9]+)*")
_FIELDS = ("id", "concept", "kind", "category", "criteria", "required", "misconceptions",
           "reference", "answer", "truth")
_TRUTH_FIELDS = ("band", "missing_required", "misconceptions_committed", "rationale")


class CaseFileError(ValueError):
    """The case file breaks its schema; the message lists every problem found."""


@dataclass(frozen=True)
class Truth:
    band: str
    # Adjacent bands that are also defensible for this answer (a band edge, written down
    # rather than argued about). Band accuracy accepts them; false mastery uses the highest.
    also_acceptable: tuple[str, ...]
    missing_required: tuple[str, ...]
    misconceptions_committed: tuple[str, ...]
    rationale: str

    @property
    def acceptable_bands(self) -> tuple[str, ...]:
        return (self.band, *self.also_acceptable)


@dataclass(frozen=True)
class Case:
    id: str
    concept: str
    kind: str
    category: str
    criteria: tuple[str, ...]
    required: tuple[str, ...]
    misconceptions: tuple[str, ...]
    reference: str
    question: str  # source quiz only, for people: the app does not send it to the grader
    answer: str
    truth: Truth
    unsure: str  # a note when the label is a judgement call, else ""


def _str_list(v) -> bool:
    return isinstance(v, list) and all(isinstance(x, str) and x.strip() for x in v)


def case_problems(d: object) -> list[str]:
    """Everything wrong with one parsed case (empty when it is valid)."""
    if not isinstance(d, dict):
        return ["not a JSON object"]
    cid = d.get("id", "?")
    out: list[str] = []

    def bad(msg: str) -> None:
        out.append(f"{cid}: {msg}")

    missing = [f for f in _FIELDS if f not in d]
    if missing:
        bad(f"missing fields {missing}")
        return out
    if not isinstance(d["id"], str) or not _ID.fullmatch(d["id"]):
        bad("id must be lowercase words joined by '-'")
    for key in ("concept", "answer"):
        if not isinstance(d[key], str) or not d[key].strip():
            bad(f"{key} must be a non-empty string")
    if d["kind"] not in KINDS:
        bad(f"kind {d['kind']!r} is not one of {KINDS}")
    if d["category"] not in CATEGORIES:
        bad(f"category {d['category']!r} is not one of {CATEGORIES}")
    for key in ("criteria", "required", "misconceptions"):
        if not _str_list(d[key]):
            bad(f"{key} must be a list of non-empty strings")
        elif len({x.strip() for x in d[key]}) != len(d[key]):
            bad(f"{key} has a duplicate item")
        elif any(x != x.strip() for x in d[key]):
            bad(f"{key} has an item with surrounding spaces")
    if not isinstance(d["reference"], str):
        bad("reference must be a string")
    if not d.get("required"):
        bad("required must list at least one element")
    if d["kind"] == "source_quiz":
        # As the app sends a source quiz: the anchor's key points are both the criteria and
        # the required elements, there are no misconceptions, and there is a reference answer.
        if d["criteria"] != d["required"]:
            bad("a source_quiz case's criteria must equal its required (the key points)")
        if d["misconceptions"]:
            bad("a source_quiz case sends no misconceptions")
        if not (isinstance(d["reference"], str) and d["reference"].strip()):
            bad("a source_quiz case needs a reference answer")
    elif d["kind"] == "self_explanation" and d["reference"]:
        bad("a self_explanation case sends no reference answer")
    for key in ("question", "unsure"):
        if key in d and not isinstance(d[key], str):
            bad(f"{key} must be a string")

    truth = d["truth"]
    if not isinstance(truth, dict):
        bad("truth must be an object")
        return out
    t_missing = [f for f in _TRUTH_FIELDS if f not in truth]
    if t_missing:
        bad(f"truth is missing {t_missing}")
        return out
    band = truth["band"]
    if band not in BANDS:
        bad(f"truth.band {band!r} is not one of {BANDS}")
    also = truth.get("also_acceptable", [])
    if not isinstance(also, list) or any(b not in BANDS for b in also):
        bad("truth.also_acceptable must be a list of bands")
    elif band in BANDS:
        if band in also or len(set(also)) != len(also):
            bad("truth.also_acceptable repeats a band")
        if any(abs(BANDS.index(b) - BANDS.index(band)) != 1 for b in also):
            bad("truth.also_acceptable may only name a band next to truth.band")
    if not isinstance(also, list):
        also = []
    for key, sent in (("missing_required", d["required"]),
                      ("misconceptions_committed", d["misconceptions"])):
        items = truth[key]
        if not isinstance(items, list) or not all(isinstance(x, str) for x in items):
            bad(f"truth.{key} must be a list of strings")
        elif not set(items) <= set(sent if isinstance(sent, list) else []):
            bad(f"truth.{key} names items that were not sent: "
                f"{sorted(set(items) - set(sent))}")
        elif len(set(items)) != len(items):
            bad(f"truth.{key} repeats an item")
    if not isinstance(truth["rationale"], str) or not truth["rationale"].strip():
        bad("truth.rationale must be a non-empty string")
    if (band == "high" or "high" in also) and (
            truth["missing_required"] or truth["misconceptions_committed"]):
        # The app caps such an answer at 0.70 or 0.50, below the high band.
        bad("a high truth band cannot miss a required element or commit a misconception")
    return out


def _case(d: dict) -> Case:
    t = d["truth"]
    return Case(
        id=d["id"], concept=d["concept"], kind=d["kind"], category=d["category"],
        criteria=tuple(d["criteria"]), required=tuple(d["required"]),
        misconceptions=tuple(d["misconceptions"]), reference=d["reference"],
        question=d.get("question", ""), answer=d["answer"],
        truth=Truth(band=t["band"], also_acceptable=tuple(t.get("also_acceptable", [])),
                    missing_required=tuple(t["missing_required"]),
                    misconceptions_committed=tuple(t["misconceptions_committed"]),
                    rationale=t["rationale"]),
        unsure=d.get("unsure", ""))


def parse_cases(text: str) -> list[Case]:
    """Parse and validate the whole file; raise CaseFileError listing every problem."""
    problems: list[str] = []
    dicts: list[dict] = []
    for n, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            d = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"line {n}: not JSON ({exc.msg})")
            continue
        found = case_problems(d)
        problems += [f"line {n}: {p}" for p in found]
        if not found:
            dicts.append(d)
    seen: set[str] = set()
    for d in dicts:
        if d["id"] in seen:
            problems.append(f"duplicate id {d['id']}")
        seen.add(d["id"])
    if not dicts and not problems:
        problems.append("no cases")
    if problems:
        raise CaseFileError("case file problems:\n" + "\n".join(problems))
    return [_case(d) for d in dicts]


def load_cases(path: Path) -> list[Case]:
    return parse_cases(Path(path).read_text(encoding="utf-8"))
