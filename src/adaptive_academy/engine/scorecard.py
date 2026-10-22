"""The quality scorecard on the Usage page: is each model doing its job?

Read-only. Per time window (llm/usage.window_starts: today, last 7 days, last 30 days, all
time) it reports, from rows the app already writes:

Per feature and per model (LLMUsage rows):
  calls             model calls recorded.
  cost_per_call_usd spend (reported cost where the service reports one, else list price;
                    llm/usage.effective_cost) divided by the calls that HAVE a cost. Calls on
                    a model with no known price are left out of both sides, so they don't
                    pull the average down. None when no call had a cost.
  recorded_calls    calls with an outcome (LLMUsage.outcome). Rows from before that column,
                    Agent SDK calls and research searches have none; they are left out of the
                    counts below and their rates, never counted as fine.
  refusals          outcome "refusal": the model declined.
  empty_replies     outcome "empty": no text and no tool call.
  cut_offs          outcome "cut_off": stopped at max_tokens or the context window.
  invalid_outputs   outcome "invalid_output": a structured answer that was not usable (not
                    the tool call, the wrong shape, or not JSON), counted per call, so it
                    includes answers the one corrective retry then fixed. Only the
                    structured-output path (complete_json) records it: graders call
                    llm.complete and are checked afterwards (engine/grade_gate.py), so a grade
                    in the wrong format shows under grading health (rule J1 and the rest),
                    not here, where its call reads "ok".

Grading (GRADING_FEATURES' usage, Assessment rows, and grade:* AgentEvents):
  cost_per_assessment_usd  all spend recorded under a grading feature, divided by the
                    grades written in the window (graded_assessments: one per Assessment row,
                    but one per grader call for artifact reviews; see _graded_assessments).
                    Unpriced grading calls are left out of the spend; the page says so when
                    there are any. A grading feature is one whose
                    route writes Assessment rows: assess (self-explanation, calibration,
                    source quiz), decay (recall), teach, productive_failure, deliverables
                    (artifact review), roleplay and paper_probe. Their other calls (a
                    roleplay persona's turns, a paper probe's questions, a productive-failure
                    challenge) count too: they are part of what one grade costs. Rows on the
                    demo topic are not counted (no model graded them). None when the window
                    has no assessment, no grading call, or only unpriced grading calls.
  first_attempts    grade:check events at attempt 1: grader answers checked.
  regenerations_per_grade  grade:regenerated over first_attempts.
  rejected          grade:rejected events, split into rejected_failed_checks (failed its
                    checks twice; rejected_share is these over first_attempts) and
                    rejected_stopped (the grader refused or was cut off; no check ran).
  top_failed_rules  the FAIL rule ids (engine/output_checks.py) most often named in
                    grade:check events, top five, most common first. WARN ids are left out.

Tutor guard (guard:* AgentEvents, engine/solution_guard.py):
  checks            guard:solution_checked: pre-attempt drafts reviewed.
  blocked_share     guard:solution_blocked over checks.
  fallbacks         guard:fallback: the stored reply was the guard's fallback question.
  unavailable_share guard:unavailable over checks: the model check failed and the keyword
                    screen decided alone. Only reply checks emit guard:unavailable (one per
                    guard:solution_checked at most), so this stays within 0 to 1.
  attempt_unavailable  guard:attempt_unavailable: the check on a submitted attempt could
                    not run, so an attempt was not recorded (fail closed). Counted on its
                    own, with no share: it has nothing to do with replies checked.

AgentEvents carry neither a feature nor a model, so the grading and guard numbers are per
window only. The event query reads only the kinds above through ix_agentevent_kind_created_at,
so its cost follows the number of quality events, not the size of the whole trace.
"""

import re
from collections import Counter
from datetime import datetime

from sqlalchemy import and_, case, func, true
from sqlmodel import Session, select

from adaptive_academy.llm import model_catalog
from adaptive_academy.llm.usage import (
    OUTCOME_CUT_OFF,
    OUTCOME_EMPTY,
    OUTCOME_INVALID,
    OUTCOME_REFUSAL,
    db_time,
    effective_cost,
    window_starts,
)
from adaptive_academy.models import AgentEvent, Assessment, Concept, LLMUsage, Topic, Track

GRADING_FEATURES = ("assess", "decay", "teach", "productive_failure", "deliverables",
                    "roleplay", "paper_probe")

GRADE_CHECK = "grade:check"
GRADE_REGENERATED = "grade:regenerated"
GRADE_REJECTED = "grade:rejected"
GUARD_CHECKED = "guard:solution_checked"
GUARD_BLOCKED = "guard:solution_blocked"
GUARD_FALLBACK = "guard:fallback"
GUARD_UNAVAILABLE = "guard:unavailable"
GUARD_ATTEMPT_UNAVAILABLE = "guard:attempt_unavailable"
EVENT_KINDS = (GRADE_CHECK, GRADE_REGENERATED, GRADE_REJECTED, GUARD_CHECKED, GUARD_BLOCKED,
               GUARD_FALLBACK, GUARD_UNAVAILABLE, GUARD_ATTEMPT_UNAVAILABLE)
TOP_RULES = 5

# Event details these numbers read (engine/output_checks.summarize, engine/grade_gate.py);
# tests/test_quality_scorecard.py drives the real emitters so a wording change fails there.
_FIRST_ATTEMPT = " attempt=1 "
_FAILED_CHECKS = "rejected after"
_STOPPED = "stopped on attempt"
_FAIL_IDS = re.compile(r"\bFAIL ([A-Za-z0-9,]+)")


def _ratio(numerator: float, denominator: float) -> float | None:
    return numerator / denominator if denominator else None


def _count(condition) -> object:
    return func.coalesce(func.sum(case((condition, 1), else_=0)), 0)


def _since(column, start: datetime | None):
    return true() if start is None else column >= db_time(start)


def _usage_rows(session: Session, column, start: datetime | None) -> list[dict]:
    outcome = LLMUsage.outcome
    rows = session.exec(
        select(
            column.label("key"),
            func.count(LLMUsage.id).label("calls"),
            func.coalesce(func.sum(effective_cost), 0.0).label("cost_usd"),
            _count(effective_cost.is_(None)).label("unpriced_calls"),
            _count(outcome.is_not(None)).label("recorded_calls"),
            _count(outcome == OUTCOME_REFUSAL).label("refusals"),
            _count(outcome == OUTCOME_EMPTY).label("empty_replies"),
            _count(outcome == OUTCOME_CUT_OFF).label("cut_offs"),
            _count(outcome == OUTCOME_INVALID).label("invalid_outputs"),
        )
        .where(_since(LLMUsage.created_at, start))
        .group_by(column)
    ).all()
    items = []
    for r in rows:
        calls = int(r.calls)
        unpriced = int(r.unpriced_calls)
        cost = float(r.cost_usd or 0.0)
        items.append({
            "key": r.key,
            "calls": calls,
            "cost_usd": cost,
            "unpriced_calls": unpriced,
            "cost_per_call_usd": _ratio(cost, calls - unpriced),
            "recorded_calls": int(r.recorded_calls),
            "refusals": int(r.refusals),
            "empty_replies": int(r.empty_replies),
            "cut_offs": int(r.cut_offs),
            "invalid_outputs": int(r.invalid_outputs),
        })
    items.sort(key=lambda i: (-i["calls"], -i["cost_usd"], str(i["key"])))
    return items


ARTIFACT_REVIEW = "artifact_review"


def _graded_assessments(session: Session, start: datetime | None) -> int:
    """Grades written in the window: one per Assessment row, except artifact reviews, which
    count once per grader call. engine/artifact.review_artifact makes ONE grader call and
    writes one artifact_review row per phase concept, all in one loop, so a deliverable that
    covers 8 concepts would otherwise read as 8 grades. Those rows share the deliverable
    prompt, the pasted response and the grader's verdict, and are written within the same
    second; nothing else links them (no deliverable id on Assessment). So a review is
    (prompt, response, verdict, created_at to the second). Two reviews of the same
    deliverable and text stay apart by their verdict (the grader's own free text) or their
    time. A loop that straddles a second boundary would count twice: rare, and it errs
    toward a lower cost per grade only by that one review."""
    demo_concepts = (select(Concept.id)
                     .join(Track, Concept.track_id == Track.id)
                     .join(Topic, Track.topic_id == Topic.id)
                     .where(Topic.is_demo == True))  # noqa: E712 - SQL, not Python truth
    is_review = Assessment.kind == ARTIFACT_REVIEW
    review_key = func.json_array(Assessment.prompt, Assessment.response, Assessment.verdict,
                                 func.strftime("%Y-%m-%d %H:%M:%S", Assessment.created_at))
    row = session.exec(
        select(
            _count(~is_review).label("per_row"),
            func.count(func.distinct(case((is_review, review_key)))).label("reviews"),
        ).where(
            _since(Assessment.created_at, start),
            Assessment.concept_id.not_in(demo_concepts),
        )
    ).one()
    return int(row.per_row) + int(row.reviews)


def event_counts_statement(start: datetime | None):
    """One pass over the quality events in the window: every grading and guard count."""
    kind, detail = AgentEvent.kind, AgentEvent.detail

    def has(text: str):
        return func.instr(detail, text) > 0

    return select(
        _count(and_(kind == GRADE_CHECK, has(_FIRST_ATTEMPT))).label("first_attempts"),
        _count(kind == GRADE_REGENERATED).label("regenerations"),
        _count(kind == GRADE_REJECTED).label("rejected"),
        _count(and_(kind == GRADE_REJECTED, has(_FAILED_CHECKS))).label("rejected_failed"),
        _count(and_(kind == GRADE_REJECTED, has(_STOPPED))).label("rejected_stopped"),
        _count(kind == GUARD_CHECKED).label("checks"),
        _count(kind == GUARD_BLOCKED).label("blocked"),
        _count(kind == GUARD_FALLBACK).label("fallbacks"),
        _count(kind == GUARD_UNAVAILABLE).label("unavailable"),
        _count(kind == GUARD_ATTEMPT_UNAVAILABLE).label("attempt_unavailable"),
    ).where(kind.in_(EVENT_KINDS), _since(AgentEvent.created_at, start))


def _top_failed_rules(session: Session, start: datetime | None) -> list[dict]:
    details = session.exec(
        select(AgentEvent.detail).where(
            AgentEvent.kind == GRADE_CHECK,
            _since(AgentEvent.created_at, start),
            func.instr(AgentEvent.detail, " FAIL ") > 0,
        )
    ).all()
    counts: Counter[str] = Counter()
    for detail in details:
        for match in _FAIL_IDS.finditer(detail or ""):
            counts.update(i for i in match.group(1).split(",") if i)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_RULES]
    return [{"rule_id": rule, "count": n} for rule, n in ranked]


def _window(session: Session, start: datetime | None) -> dict:
    by_feature = _usage_rows(session, LLMUsage.feature, start)
    by_model = _usage_rows(session, LLMUsage.model, start)
    grading_rows = [r for r in by_feature if r["key"] in GRADING_FEATURES]
    calls = sum(r["calls"] for r in grading_rows)
    unpriced = sum(r["unpriced_calls"] for r in grading_rows)
    cost = sum(r["cost_usd"] for r in grading_rows)
    assessments = _graded_assessments(session, start)
    events = session.exec(event_counts_statement(start)).one()
    first = int(events.first_attempts)
    checks = int(events.checks)
    return {
        "by_feature": [{"feature": r.pop("key"), **r} for r in by_feature],
        "by_model": [{"model": (m := r.pop("key")), **r,
                      "experimental": model_catalog.is_experimental(m)} for r in by_model],
        "grading": {
            "calls": calls,
            "cost_usd": cost,
            "unpriced_calls": unpriced,
            "graded_assessments": assessments,
            "cost_per_assessment_usd": (cost / assessments
                                        if assessments and calls > unpriced else None),
            "first_attempts": first,
            "regenerations": int(events.regenerations),
            "regenerations_per_grade": _ratio(int(events.regenerations), first),
            "rejected": int(events.rejected),
            "rejected_failed_checks": int(events.rejected_failed),
            "rejected_stopped": int(events.rejected_stopped),
            "rejected_share": _ratio(int(events.rejected_failed), first),
            "top_failed_rules": _top_failed_rules(session, start),
        },
        "guard": {
            "checks": checks,
            "blocked": int(events.blocked),
            "blocked_share": _ratio(int(events.blocked), checks),
            "fallbacks": int(events.fallbacks),
            "unavailable": int(events.unavailable),
            "unavailable_share": _ratio(int(events.unavailable), checks),
            "attempt_unavailable": int(events.attempt_unavailable),
        },
    }


def quality_scorecard(session: Session, now: datetime | None = None) -> dict:
    """The scorecard for every window (see the module docstring for each number)."""
    return {
        "grading_features": list(GRADING_FEATURES),
        "windows": {name: _window(session, start)
                    for name, start in window_starts(now).items()},
    }
