"""The README screenshot seed (frontend/screenshots/seed_screenshots.py).

The Usage screenshot should look like a page in use: spend that grows with the window, calls
with outcomes, and a scorecard with grade checks and tutor-guard checks in it. The seed must
also leave the db without a topic, so the empty home page stays empty until the demo is added.
"""

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlmodel import select

from adaptive_academy.engine.scorecard import quality_scorecard
from adaptive_academy.llm.usage import usage_summary
from adaptive_academy.models import AgentEvent, LLMUsage, Topic

SEED = Path(__file__).resolve().parents[1] / "frontend" / "screenshots" / "seed_screenshots.py"


@pytest.fixture
def seed_module():
    spec = importlib.util.spec_from_file_location("seed_screenshots", SEED)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Mid-morning, an hour after local midnight, and a minute after it: today's rows must stay in
# today however early the run is.
@pytest.mark.parametrize("hours_into_day", [10.0, 1.0, 1 / 60])
def test_spend_grows_with_each_window(seed_module, session, hours_into_day):
    midnight = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    now = (midnight + timedelta(hours=hours_into_day)).astimezone(timezone.utc)
    seed_module.seed(session, now)
    totals = usage_summary(session, now)["totals"]
    costs = [totals[w]["cost_usd"] for w in ("today", "last_7_days", "last_30_days", "all_time")]
    assert costs[0] > 0
    assert costs == sorted(costs)
    assert len(set(costs)) == 4, costs
    stored_now = now.replace(tzinfo=None)  # created_at is stored as naive UTC
    for model in (LLMUsage, AgentEvent):
        assert all(r.created_at <= stored_now for r in session.exec(select(model)).all())


def test_calls_have_outcomes_and_the_scorecard_has_data(seed_module, session):
    rows, events = seed_module.seed(session)
    assert rows == len(session.exec(select(LLMUsage)).all())
    assert events == len(session.exec(select(AgentEvent)).all())
    for row in session.exec(select(LLMUsage)).all():
        # Research searches record no outcome, as in the app; every other call does.
        assert (row.outcome is None) == (row.operation == "research_search")

    month = quality_scorecard(session)["windows"]["last_30_days"]
    assert month["grading"]["first_attempts"] > 0
    assert month["grading"]["regenerations"] > 0
    assert month["grading"]["top_failed_rules"]
    assert month["guard"]["checks"] > 0
    assert month["guard"]["blocked"] > 0
    assert len(month["by_model"]) > 1
    assert any(r["cut_offs"] or r["invalid_outputs"] for r in month["by_feature"])
    assert session.exec(select(Topic)).first() is None
