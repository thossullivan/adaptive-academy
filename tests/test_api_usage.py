"""GET /api/usage aggregation, the 429 budget response, and route → feature attribution."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.llm import usage
from adaptive_academy.models import Concept, LLMUsage, Topic, Track

NOW = datetime.now(timezone.utc)


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")


def _row(session, *, cost, when, backend="anthropic", model="claude-sonnet-4-6",
         feature=None, inp=100, out=10, searches=0):
    session.add(LLMUsage(
        created_at=when, backend=backend, model=model, role="reasoning",
        operation="complete", feature=feature, input_tokens=inp, output_tokens=out,
        cache_read_input_tokens=1, cache_creation_input_tokens=2,
        web_search_requests=searches, cost_usd=cost,
    ))
    session.commit()


def test_usage_empty_database(client, monkeypatch):
    monkeypatch.setattr(usage.settings, "daily_budget_usd", None)
    r = client.get("/api/usage")
    assert r.status_code == 200
    body = r.json()
    for window in ("today", "last_7_days", "last_30_days", "all_time"):
        t = body["totals"][window]
        assert t["calls"] == 0 and t["cost_usd"] == 0 and t["unpriced_calls"] == 0
    assert body["by_feature"] == [] and body["by_model"] == []
    assert body["budget"] == {"limit_usd": None, "spent_today_usd": 0,
                              "remaining_usd": None, "exceeded": False}
    assert body["backend"] in {"anthropic", "agent_sdk"}


def test_usage_windows_breakdowns_and_budget(client, session, monkeypatch):
    monkeypatch.setattr(usage.settings, "daily_budget_usd", 2.0)
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    _row(session, cost=0.50, when=NOW, feature="tutor", searches=1)
    _row(session, cost=None, when=NOW, model="claude-imaginary-9", feature="tutor")
    _row(session, cost=0.25, when=NOW, backend="agent_sdk", feature="research")
    _row(session, cost=1.00, when=NOW - timedelta(days=3), feature="research")
    _row(session, cost=2.00, when=NOW - timedelta(days=10), feature="assess")
    _row(session, cost=4.00, when=NOW - timedelta(days=40))

    body = client.get("/api/usage").json()
    totals = body["totals"]
    assert totals["today"]["calls"] == 3
    assert totals["today"]["cost_usd"] == pytest.approx(0.75)
    assert totals["today"]["unpriced_calls"] == 1
    assert totals["today"]["web_search_requests"] == 1
    assert totals["today"]["input_tokens"] == 300
    assert totals["today"]["output_tokens"] == 30
    assert totals["today"]["cache_read_input_tokens"] == 3
    assert totals["today"]["cache_creation_input_tokens"] == 6
    # Subscription (agent_sdk) cost is reported separately from API-key spend.
    assert totals["today"]["api_cost_usd"] == pytest.approx(0.50)
    assert totals["last_7_days"]["cost_usd"] == pytest.approx(1.75)
    assert totals["last_30_days"]["cost_usd"] == pytest.approx(3.75)
    assert totals["all_time"]["cost_usd"] == pytest.approx(7.75)
    assert totals["all_time"]["calls"] == 6

    by_feature = {f["feature"]: f for f in body["by_feature"]}
    assert set(by_feature) == {"tutor", "research", "assess"}  # 30-day window
    assert by_feature["research"]["cost_usd"] == pytest.approx(1.25)
    assert by_feature["tutor"]["unpriced_calls"] == 1
    # Sorted by cost, most expensive first.
    assert [f["feature"] for f in body["by_feature"]] == ["assess", "research", "tutor"]

    by_model = {m["model"]: m for m in body["by_model"]}
    assert by_model["claude-imaginary-9"]["cost_usd"] == 0
    assert by_model["claude-imaginary-9"]["unpriced_calls"] == 1
    assert by_model["claude-sonnet-4-6"]["calls"] == 4

    assert body["budget"] == {"limit_usd": 2.0, "spent_today_usd": pytest.approx(0.5),
                              "remaining_usd": pytest.approx(1.5), "exceeded": False}
    assert body["backend"] == "anthropic"


def test_unattributed_calls_group_under_null_feature(client, session, monkeypatch):
    monkeypatch.setattr(usage.settings, "daily_budget_usd", None)
    _row(session, cost=0.1, when=NOW, feature=None)
    body = client.get("/api/usage").json()
    assert body["by_feature"][0]["feature"] is None


def _seed_conversation(client, session) -> int:
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    convo = client.post("/api/conversations", json={"topic_id": topic.id,
                                                    "concept_id": concept.id})
    assert convo.status_code == 200
    return convo.json()["id"]


def _fake_anthropic(monkeypatch, calls):
    class _Messages:
        def create(self, **kw):
            calls.append(kw)
            return SimpleNamespace(
                content=[SimpleNamespace(type="text", text="What have you tried?")],
                usage=SimpleNamespace(input_tokens=500, output_tokens=40,
                                      cache_creation_input_tokens=0,
                                      cache_read_input_tokens=0, server_tool_use=None),
            )

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr("adaptive_academy.llm.anthropic_client.Anthropic", _FakeAnthropic)


def test_tutor_route_records_usage_with_feature_label(client, session, api_key, monkeypatch):
    monkeypatch.setattr(usage.settings, "daily_budget_usd", None)
    calls: list = []
    _fake_anthropic(monkeypatch, calls)
    cid = _seed_conversation(client, session)
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "softmax?"})
    assert r.status_code == 200, r.text
    assert calls
    session.expire_all()
    rows = session.exec(select(LLMUsage)).all()
    assert rows and {row.feature for row in rows} == {"tutor"}
    assert all(row.backend == "anthropic" for row in rows)


def test_solution_guard_call_is_recorded_on_the_copy_role_under_tutor(
        client, session, api_key, monkeypatch):
    # A pre-attempt tutor reply is checked by the solution guard: its own model call, on the
    # copy role (Haiku), recorded like any other call and attributed to the tutor feature.
    monkeypatch.setattr(usage.settings, "daily_budget_usd", None)
    monkeypatch.setattr(usage.settings, "reasoning_model", "")
    monkeypatch.setattr(usage.settings, "copy_model", "")
    calls: list = []

    class _Messages:
        def create(self, **kw):
            calls.append(kw)
            if kw.get("tool_choice"):  # the guard's structured check
                block = SimpleNamespace(type="tool_use", id="toolu_g", name=kw["tools"][0]["name"],
                                        input={"gives_away_solution": False, "reason": "a hint"})
            else:
                block = SimpleNamespace(type="text", text="What have you tried?")
            return SimpleNamespace(
                content=[block], stop_reason="end_turn",
                usage=SimpleNamespace(input_tokens=500, output_tokens=40,
                                      cache_creation_input_tokens=0,
                                      cache_read_input_tokens=0, server_tool_use=None),
            )

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr("adaptive_academy.llm.anthropic_client.Anthropic", _FakeAnthropic)
    cid = _seed_conversation(client, session)
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "softmax?"})
    assert r.status_code == 200, r.text
    assert ("guard:solution_checked", "source=model gives_away=false") in [
        (e["kind"], e["detail"]) for e in r.json()["events"]]
    session.expire_all()
    rows = {(row.role, row.operation, row.model, row.feature)
            for row in session.exec(select(LLMUsage)).all()}
    assert rows == {("reasoning", "complete", "claude-sonnet-5-5", "tutor"),
                    ("copy", "complete_json", "claude-haiku-5-5", "tutor")}


def test_over_budget_is_a_legible_429(client, session, api_key, monkeypatch):
    monkeypatch.setattr(usage.settings, "daily_budget_usd", 1.0)
    _row(session, cost=1.25, when=NOW)
    calls: list = []
    _fake_anthropic(monkeypatch, calls)
    cid = _seed_conversation(client, session)
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "softmax?"})
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert "$1.25" in detail and "$1.00" in detail
    assert "AA_DAILY_BUDGET_USD" in detail
    assert calls == []
    budget = client.get("/api/usage").json()["budget"]
    assert budget["exceeded"] is True and budget["remaining_usd"] == 0


def test_unpriced_model_under_a_limit_is_a_legible_429(client, session, api_key, monkeypatch):
    monkeypatch.setattr(usage.settings, "daily_budget_usd", 5.0)
    monkeypatch.setattr(usage.settings, "reasoning_model", "claude-unpriced-test")
    calls: list = []
    _fake_anthropic(monkeypatch, calls)
    cid = _seed_conversation(client, session)
    r = client.post(f"/api/conversations/{cid}/messages", json={"content": "softmax?"})
    assert r.status_code == 429
    detail = r.json()["detail"]
    assert "claude-unpriced-test" in detail and "no known price" in detail
    assert "AA_DAILY_BUDGET_USD" in detail
    assert calls == []


def test_openrouter_usage_prefers_reported_cost_and_flags_experimental_models(
        client, session, monkeypatch):
    monkeypatch.setattr(usage.settings, "daily_budget_usd", 1.0)
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    # A Claude call where OpenRouter's charge (with its fee) differs from list price, and a
    # call on a model with no list price at all.
    session.add(LLMUsage(created_at=NOW, backend="openrouter",
                         model="anthropic/claude-sonnet-5.5", role="reasoning",
                         operation="complete", cost_usd=0.10, reported_cost_usd=0.12))
    session.add(LLMUsage(created_at=NOW, backend="openrouter", model="deepseek/deepseek-v4",
                         role="reasoning", operation="complete", cost_usd=None,
                         reported_cost_usd=0.03))
    session.commit()
    _row(session, cost=0.50, when=NOW)  # an earlier Anthropic-backend call today

    body = client.get("/api/usage").json()
    assert body["backend"] == "openrouter"
    today = body["totals"]["today"]
    assert today["cost_usd"] == pytest.approx(0.65)
    assert today["api_cost_usd"] == pytest.approx(0.65)  # both backends are key-billed
    assert today["unpriced_calls"] == 0
    assert body["budget"]["spent_today_usd"] == pytest.approx(0.65)
    assert usage.spent_today_usd() == pytest.approx(0.65)
    by_model = {m["model"]: m for m in body["by_model"]}
    assert by_model["anthropic/claude-sonnet-5.5"]["cost_usd"] == pytest.approx(0.12)
    assert by_model["anthropic/claude-sonnet-5.5"]["experimental"] is False
    assert by_model["deepseek/deepseek-v4"]["experimental"] is True
    assert by_model["claude-sonnet-4-6"]["experimental"] is False
