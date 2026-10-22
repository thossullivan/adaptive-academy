"""The Usage page's quality scorecard (engine/scorecard.py, GET /api/usage/quality).

Every number is checked on a seeded database, per window, including empty windows and the
divisions that have nothing to divide by. The grading and guard numbers are read from events
written by the real emitters (engine/grade_gate.py, engine/solution_guard.py), so a change to
their wording that the scorecard can no longer read fails here.
"""

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.engine import scorecard
from adaptive_academy.engine.grade_gate import checked_completion
from adaptive_academy.engine.output_checks import OUTCOME_RUBRIC, GradeCheckError
from adaptive_academy.engine.solution_guard import FALLBACK, REGENERATE, SolutionGuard
from adaptive_academy.llm.types import LLMResponse, StructuredOutputError
from adaptive_academy.models import AgentEvent, Assessment, Concept, LLMUsage, Topic, Track

NOW = datetime.now(timezone.utc)
WINDOWS = ("today", "last_7_days", "last_30_days", "all_time")
OUTCOME_OK = '{"result": "Passed", "summary": "Held up under questions."}'


@pytest.fixture
def world(session: Session):
    """A real topic and a demo topic, one concept each."""
    real = Topic(title="Real")
    demo = Topic(title="Demo", is_demo=True)
    session.add_all([real, demo])
    session.flush()
    ids = {}
    for name, topic in (("real", real), ("demo", demo)):
        track = Track(topic_id=topic.id, title="t")
        session.add(track)
        session.flush()
        concept = Concept(track_id=track.id, name=name)
        session.add(concept)
        session.flush()
        ids[name] = concept.id
    ids["topic"] = real.id
    session.commit()
    return ids


def _usage(session, *, feature="tutor", model="claude-sonnet-4-6", cost=0.01, days=0,
           outcome="ok", backend="anthropic", reported=None):
    session.add(LLMUsage(created_at=NOW - timedelta(days=days, minutes=1), backend=backend,
                         model=model, role="reasoning", operation="complete",
                         feature=feature, cost_usd=cost, reported_cost_usd=reported,
                         outcome=outcome))


def _assessment(session, concept_id, *, days=0):
    session.add(Assessment(concept_id=concept_id, kind="self_explanation", prompt="p",
                           score=0.5, created_at=NOW - timedelta(days=days, minutes=1)))


def _emitter(session, topic_id, days=0):
    when = NOW - timedelta(days=days, minutes=1)

    def emit(kind, detail=""):
        session.add(AgentEvent(topic_id=topic_id, kind=kind, detail=detail, created_at=when))

    return emit


class _Scripted:
    def __init__(self, *responses):
        self._responses = list(responses)

    def complete(self, system, messages, tools):
        item = self._responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item if isinstance(item, LLMResponse) else LLMResponse(text=item,
                                                                      stop_reason="end_turn")


def _grade(session, topic_id, *answers, days=0):
    """Run the real grade gate over scripted answers; swallow its rejection."""
    try:
        checked_completion(session, _Scripted(*answers), system="s", user="u",
                           rubric=OUTCOME_RUBRIC, emit=_emitter(session, topic_id, days))
    except (GradeCheckError, StructuredOutputError):
        pass
    session.commit()


def _card(session):
    return scorecard.quality_scorecard(session, now=NOW)


# --- empty database ---------------------------------------------------------------------


def test_empty_database_has_no_rows_and_no_ratios(session):
    card = _card(session)
    assert card["grading_features"] == list(scorecard.GRADING_FEATURES)
    assert set(card["windows"]) == set(WINDOWS)
    for name in WINDOWS:
        w = card["windows"][name]
        assert w["by_feature"] == [] and w["by_model"] == []
        g = w["grading"]
        assert (g["calls"], g["cost_usd"], g["graded_assessments"]) == (0, 0.0, 0)
        assert g["cost_per_assessment_usd"] is None
        assert (g["first_attempts"], g["regenerations"], g["rejected"]) == (0, 0, 0)
        assert g["regenerations_per_grade"] is None
        assert g["rejected_share"] is None
        assert g["top_failed_rules"] == []
        guard = w["guard"]
        assert (guard["checks"], guard["blocked"], guard["fallbacks"],
                guard["unavailable"]) == (0, 0, 0, 0)
        assert guard["blocked_share"] is None and guard["unavailable_share"] is None


# --- calls, cost per call, and how calls ended -------------------------------------------


def test_feature_and_model_rows_count_calls_cost_and_outcomes(session, world):
    _usage(session, feature="tutor", cost=0.02, outcome="ok")
    _usage(session, feature="tutor", cost=0.04, outcome="refusal")
    _usage(session, feature="tutor", cost=None, outcome="empty",
           model="claude-imaginary-9")  # unpriced: not in the per-call denominator
    _usage(session, feature="research", cost=0.10, outcome="invalid_output")
    _usage(session, feature="research", cost=0.10, outcome="cut_off")
    _usage(session, feature="research", cost=0.10, outcome=None)  # before outcomes existed
    _usage(session, feature="research", cost=0.30, outcome="invalid_output", days=3)
    _usage(session, feature=None, cost=0.05, days=40)
    session.commit()

    today = _card(session)["windows"]["today"]
    tutor = next(r for r in today["by_feature"] if r["feature"] == "tutor")
    assert tutor["calls"] == 3 and tutor["unpriced_calls"] == 1
    assert tutor["cost_usd"] == pytest.approx(0.06)
    assert tutor["cost_per_call_usd"] == pytest.approx(0.03)  # 0.06 over 2 priced calls
    assert tutor["recorded_calls"] == 3
    assert (tutor["refusals"], tutor["empty_replies"], tutor["cut_offs"],
            tutor["invalid_outputs"]) == (1, 1, 0, 0)
    research = next(r for r in today["by_feature"] if r["feature"] == "research")
    assert research["calls"] == 3 and research["recorded_calls"] == 2
    assert (research["invalid_outputs"], research["cut_offs"]) == (1, 1)
    assert research["cost_per_call_usd"] == pytest.approx(0.10)

    models = {r["model"]: r for r in today["by_model"]}
    assert models["claude-sonnet-4-6"]["calls"] == 5
    assert models["claude-sonnet-4-6"]["refusals"] == 1
    assert models["claude-imaginary-9"]["cost_per_call_usd"] is None  # no priced call
    assert models["claude-imaginary-9"]["empty_replies"] == 1

    week = _card(session)["windows"]["last_7_days"]
    research7 = next(r for r in week["by_feature"] if r["feature"] == "research")
    assert research7["calls"] == 4 and research7["invalid_outputs"] == 2
    all_time = _card(session)["windows"]["all_time"]
    background = next(r for r in all_time["by_feature"] if r["feature"] is None)
    assert background["calls"] == 1 and background["recorded_calls"] == 1
    assert not any(r["feature"] is None for r in week["by_feature"])


def test_reported_cost_wins_and_experimental_models_are_flagged(session):
    _usage(session, model="deepseek/deepseek-v4", backend="openrouter", cost=None,
           reported=0.003)
    session.commit()
    [row] = _card(session)["windows"]["today"]["by_model"]
    assert row["experimental"] is True
    assert row["cost_per_call_usd"] == pytest.approx(0.003)
    assert row["unpriced_calls"] == 0


# --- cost per graded assessment -----------------------------------------------------------


def test_cost_per_graded_assessment(session, world):
    _usage(session, feature="assess", cost=0.30)
    _usage(session, feature="roleplay", cost=0.10)
    _usage(session, feature="paper_probe", cost=0.20)
    _usage(session, feature="tutor", cost=5.00)  # not a grading feature
    _usage(session, feature="assess", cost=1.00, days=10)
    _assessment(session, world["real"])
    _assessment(session, world["real"])
    _assessment(session, world["demo"])  # the demo topic's rows were never graded by a model
    _assessment(session, world["real"], days=10)
    session.commit()

    windows = _card(session)["windows"]
    g = windows["today"]["grading"]
    assert g["calls"] == 3
    assert g["cost_usd"] == pytest.approx(0.60)
    assert g["graded_assessments"] == 2
    assert g["cost_per_assessment_usd"] == pytest.approx(0.30)
    g30 = windows["last_30_days"]["grading"]
    assert g30["graded_assessments"] == 3
    assert g30["cost_per_assessment_usd"] == pytest.approx(1.60 / 3)


def test_cost_per_graded_assessment_has_no_value_without_both_sides(session, world):
    # Grading spend but no assessment written (every grade was rejected, say).
    _usage(session, feature="assess", cost=0.30)
    # An assessment from 10 days ago with no grading call recorded in that window.
    _assessment(session, world["real"], days=10)
    _usage(session, feature="teach", cost=None, days=20)  # unpriced spend only
    _assessment(session, world["real"], days=20)
    session.commit()
    windows = _card(session)["windows"]
    assert windows["today"]["grading"]["graded_assessments"] == 0
    assert windows["today"]["grading"]["cost_per_assessment_usd"] is None
    # 7 days: no calls, no assessments.
    assert windows["last_7_days"]["grading"]["cost_per_assessment_usd"] is None
    # 30 days: one priced call and two assessments.
    assert windows["last_30_days"]["grading"]["cost_per_assessment_usd"] == pytest.approx(0.15)


def test_unpriced_grading_spend_gives_no_cost_per_assessment(session, world):
    _usage(session, feature="teach", cost=None)
    _assessment(session, world["real"])
    session.commit()
    g = _card(session)["windows"]["today"]["grading"]
    assert g["unpriced_calls"] == 1
    assert g["cost_per_assessment_usd"] is None


# --- grading health ---------------------------------------------------------------------


def test_grading_health_from_the_real_grade_gate(session, world):
    topic = world["topic"]
    _grade(session, topic, OUTCOME_OK)  # passes first time
    _grade(session, topic, "{}", OUTCOME_OK)  # O1,O2 fail, then regenerated
    _grade(session, topic, '{"result": "x"}', '{"summary": "y"}')  # O2 then O1: rejected
    _grade(session, topic, LLMResponse(text="", stop_reason="refusal"))  # stopped at once
    _grade(session, topic, "not json", "{}", days=3)  # J1, then O1,O2: rejected

    windows = _card(session)["windows"]
    g = windows["today"]["grading"]
    assert g["first_attempts"] == 3  # the refusal never reached a check
    assert g["regenerations"] == 2
    assert g["regenerations_per_grade"] == pytest.approx(2 / 3)
    assert g["rejected"] == 2
    assert g["rejected_failed_checks"] == 1 and g["rejected_stopped"] == 1
    assert g["rejected_share"] == pytest.approx(1 / 3)
    # Most common first; ties by rule id.
    assert g["top_failed_rules"] == [{"rule_id": "O1", "count": 2},
                                     {"rule_id": "O2", "count": 2}]
    g7 = windows["last_7_days"]["grading"]
    assert g7["first_attempts"] == 4 and g7["rejected"] == 3
    assert g7["top_failed_rules"][0] == {"rule_id": "O1", "count": 3}
    assert {"rule_id": "J1", "count": 1} in g7["top_failed_rules"]


def test_top_failed_rules_ignore_warnings_and_keep_five(session, world):
    emit = _emitter(session, world["topic"])
    for ids in ("G1", "G1,G2", "G3", "G4", "G5", "G6", "G1"):
        emit("grade:check", f"grade attempt=1 fail FAIL {ids} WARN G8,G10")
    emit("grade:check", "grade attempt=2 pass WARN G8")
    session.commit()
    g = _card(session)["windows"]["today"]["grading"]
    assert g["first_attempts"] == 7
    assert g["top_failed_rules"] == [
        {"rule_id": "G1", "count": 3}, {"rule_id": "G2", "count": 1},
        {"rule_id": "G3", "count": 1}, {"rule_id": "G4", "count": 1},
        {"rule_id": "G5", "count": 1}]


# --- tutor guard ------------------------------------------------------------------------


class _Boom:
    def complete(self, *a, **kw):
        raise RuntimeError("down")


def test_guard_numbers_from_the_real_solution_guard(session, world):
    emit = _emitter(session, world["topic"])
    leak = "Here's the full solution: x = 4."
    # Screen only (no model check): a leak is blocked, regenerated, then falls back.
    guard = SolutionGuard(concept="c", learner_text="?", llm=None, emit=emit)
    assert guard.review(leak) == REGENERATE
    assert guard.review(leak) == FALLBACK
    # A clean reply, with the model check failing: the screen decides.
    unavailable = SolutionGuard(concept="c", learner_text="?", llm=_Boom(), emit=emit)
    unavailable.review("What would your first step be?")
    session.commit()

    guard_card = _card(session)["windows"]["today"]["guard"]
    assert guard_card["checks"] == 3
    assert guard_card["blocked"] == 2
    assert guard_card["blocked_share"] == pytest.approx(2 / 3)
    assert guard_card["fallbacks"] == 1
    assert guard_card["unavailable"] == 1
    assert guard_card["unavailable_share"] == pytest.approx(1 / 3)
    assert _card(session)["windows"]["today"]["guard"] == \
        _card(session)["windows"]["all_time"]["guard"]


def test_old_guard_events_fall_out_of_short_windows(session, world):
    emit = _emitter(session, world["topic"], days=10)
    emit("guard:solution_checked", "source=model gives_away=false")
    session.commit()
    windows = _card(session)["windows"]
    assert windows["last_7_days"]["guard"]["checks"] == 0
    assert windows["last_7_days"]["guard"]["blocked_share"] is None
    assert windows["last_30_days"]["guard"]["checks"] == 1
    assert windows["last_30_days"]["guard"]["blocked_share"] == 0.0


# --- efficiency and the endpoint --------------------------------------------------------


def _plan(session, stmt) -> str:
    compiled = stmt.compile(dialect=session.get_bind().dialect,
                            compile_kwargs={"render_postcompile": True})
    params = [compiled.params[name] for name in compiled.positiontup]
    params = [str(p) if isinstance(p, datetime) else p for p in params]
    rows = session.connection().exec_driver_sql(
        f"EXPLAIN QUERY PLAN {compiled}", tuple(params)).fetchall()
    return " ".join(str(r) for r in rows)


@pytest.mark.parametrize("start", [NOW - timedelta(days=7), None])
def test_event_counts_use_the_kind_index(session, start):
    # Read through the (kind, created_at) index, not a scan of the whole trace.
    plan = _plan(session, scorecard.event_counts_statement(start))
    assert "ix_agentevent_kind_created_at" in plan
    assert "SEARCH agentevent USING INDEX ix_agentevent_kind_created_at" in plan


def test_scorecard_stays_quick_on_a_large_trace(session, world):
    # Thousands of ordinary trace events plus quality events: the scorecard reads only the
    # quality kinds, so this stays well under the page's budget.
    session.connection().exec_driver_sql(
        "INSERT INTO agentevent (topic_id, kind, detail, created_at) "
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 30000) "
        "SELECT ?, CASE WHEN i % 10 = 0 THEN 'grade:check' ELSE 'llm_call' END, "
        "CASE WHEN i % 20 = 0 THEN 'grade attempt=1 fail FAIL G1' "
        "WHEN i % 10 = 0 THEN 'grade attempt=1 pass' ELSE 'step=1' END, "
        "datetime('now', '-' || (i % 60) || ' days') FROM n", (world["topic"],))
    session.commit()
    started = time.perf_counter()
    card = _card(session)
    elapsed = time.perf_counter() - started
    assert card["windows"]["all_time"]["grading"]["first_attempts"] == 3000
    assert card["windows"]["all_time"]["grading"]["top_failed_rules"] == [
        {"rule_id": "G1", "count": 1500}]
    assert elapsed < 2.0


def test_scorecard_endpoint(session, world):
    _usage(session, feature="assess", cost=0.30, outcome="invalid_output")
    _assessment(session, world["real"])
    session.commit()
    app.dependency_overrides[get_session] = lambda: session
    try:
        r = TestClient(app).get("/api/usage/quality")
    finally:
        app.dependency_overrides.clear()
    assert r.status_code == 200
    body = r.json()
    today = body["windows"]["today"]
    assert today["by_feature"][0]["feature"] == "assess"
    assert today["by_feature"][0]["invalid_outputs"] == 1
    assert today["by_model"][0]["experimental"] is False
    assert today["grading"]["cost_per_assessment_usd"] == pytest.approx(0.30)
    assert body["grading_features"] == list(scorecard.GRADING_FEATURES)
