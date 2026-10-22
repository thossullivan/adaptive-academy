"""Review fixes for the OpenRouter backend: the daily limit can't be bypassed by a missing
cost, an Anthropic key never reaches openrouter.ai from either backend, agent_sdk in the
container is refused legibly, and mistaken configuration is named. All offline: requests go
through the real SDK to an httpx MockTransport."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from adaptive_academy.api.app import app, setup_problems
from adaptive_academy.api.deps import get_session
from adaptive_academy.llm import model_catalog, pricing, usage
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.backends import ANTHROPIC, OPENROUTER, anthropic_base_url
from adaptive_academy.llm.errors import describe_llm_error
from adaptive_academy.llm.keys import MissingAPIKeyError, key_problem, require_api_key
from adaptive_academy.models import Concept, LLMUsage, Topic, Track
from adaptive_academy.settings import settings

ANTHROPIC_KEY = "sk-ant-api03-test-not-a-real-key"
OPENROUTER_KEY = "sk-or-v1-test-not-a-real-key"
USER = {"role": "user", "content": "What does the learning rate do?"}
TEXT = [{"type": "text", "text": "Try a smaller step."}]


def _message(model, *, usage_extra=None, content=TEXT, stop_reason="end_turn"):
    usage_body = {"input_tokens": 1000, "output_tokens": 100, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0, **(usage_extra or {})}
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": usage_body}


class Wire:
    def __init__(self, *bodies):
        self.bodies = list(bodies)
        self.requests: list[httpx.Request] = []

    def _handle(self, request):
        self.requests.append(request)
        return httpx.Response(200, json=self.bodies[min(len(self.requests),
                                                         len(self.bodies)) - 1])

    def http_client(self):
        return httpx.Client(transport=httpx.MockTransport(self._handle))


@pytest.fixture
def openrouter(monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", OPENROUTER_KEY)
    monkeypatch.setattr(settings, "reasoning_model", "")
    monkeypatch.setattr(settings, "copy_model", "")
    monkeypatch.setattr(settings, "daily_budget_usd", None)


def _rows(session):
    return list(session.exec(select(LLMUsage).order_by(LLMUsage.id)).all())


# --- 1. the daily limit can't be bypassed by a response without a cost --------------------


@pytest.mark.parametrize(("slug", "anthropic_id"), [
    ("anthropic/claude-sonnet-5.5", "claude-sonnet-5-5"),
    ("~anthropic/claude-sonnet-5.5", "claude-sonnet-5-5"),
    ("anthropic/claude-haiku-5.5:beta", "claude-haiku-5-5"),
    ("Anthropic/Claude-Opus-5.5", "claude-opus-5-5"),
    ("claude-sonnet-5-5", "claude-sonnet-5-5"),
    ("deepseek/deepseek-v4", "deepseek/deepseek-v4"),
])
def test_openrouter_claude_slugs_use_the_anthropic_list_price(slug, anthropic_id):
    assert pricing.anthropic_model_id(slug) == anthropic_id
    assert pricing.price_for(slug) is pricing.price_for(anthropic_id)


def test_priced_claude_slug_without_a_reported_cost_records_list_price(session, openrouter,
                                                                       monkeypatch):
    monkeypatch.setattr(settings, "daily_budget_usd", 5.0)
    llm = AnthropicLLMClient(http_client=Wire(
        _message("anthropic/claude-sonnet-5.5")).http_client())
    llm.complete("S", [USER], [])
    [row] = _rows(session)
    assert row.reported_cost_usd is None
    # 1000 in x $2 + 100 out x $10 per MTok (Sonnet 5.5 list price).
    assert row.cost_usd == pytest.approx(0.003)
    assert usage.spent_today_usd() == pytest.approx(0.003)
    llm.complete("S", [USER], [])  # still allowed: its spend is counted at list price


def test_unpriced_model_without_a_reported_cost_is_refused_next_time(session, openrouter,
                                                                    monkeypatch):
    monkeypatch.setattr(settings, "daily_budget_usd", 5.0)
    monkeypatch.setattr(settings, "reasoning_model", "deepseek/deepseek-v4")
    wire = Wire(_message("deepseek/deepseek-v4"))
    llm = AnthropicLLMClient(http_client=wire.http_client())
    llm.complete("S", [USER], [])  # the first call can't know: it runs
    [row] = _rows(session)
    assert (row.cost_usd, row.reported_cost_usd) == (None, None)
    with pytest.raises(usage.UnreportedCostError) as caught:
        llm.complete("S", [USER], [])
    assert len(wire.requests) == 1
    failure = describe_llm_error(caught.value)
    assert (failure.category, failure.status_code) == ("budget", 429)
    assert "deepseek/deepseek-v4" in failure.detail
    assert "did not report the cost" in failure.detail
    assert "AA_DAILY_BUDGET_USD" in failure.detail


def test_unpriced_model_with_reported_costs_keeps_running(session, openrouter, monkeypatch):
    monkeypatch.setattr(settings, "daily_budget_usd", 5.0)
    monkeypatch.setattr(settings, "reasoning_model", "deepseek/deepseek-v4")
    llm = AnthropicLLMClient(http_client=Wire(
        _message("deepseek/deepseek-v4", usage_extra={"cost": 0.001})).http_client())
    for _ in range(3):
        llm.complete("S", [USER], [])
    assert [r.reported_cost_usd for r in _rows(session)] == [0.001] * 3


def test_byok_charge_adds_the_upstream_cost(session, openrouter):
    byok = {"cost": 0.0002, "is_byok": True,
            "cost_details": {"upstream_inference_cost": 0.004,
                             "upstream_inference_prompt_cost": 0.002,
                             "upstream_inference_completions_cost": 0.002}}
    AnthropicLLMClient(http_client=Wire(_message(
        "anthropic/claude-sonnet-5.5", usage_extra=byok)).http_client()).complete("S", [USER], [])
    [row] = _rows(session)
    assert row.reported_cost_usd == pytest.approx(0.0042)


def test_byok_without_the_upstream_cost_falls_back_to_list_price(session, openrouter):
    byok = {"cost": 0.0002, "is_byok": True, "cost_details": {"upstream_inference_cost": None}}
    AnthropicLLMClient(http_client=Wire(_message(
        "anthropic/claude-sonnet-5.5", usage_extra=byok)).http_client()).complete("S", [USER], [])
    [row] = _rows(session)
    assert row.reported_cost_usd is None
    assert row.cost_usd == pytest.approx(0.003)


def test_not_byok_ignores_the_upstream_field(session, openrouter):
    plain = {"cost": 0.0031, "is_byok": False, "cost_details": {"upstream_inference_cost": 9.0}}
    AnthropicLLMClient(http_client=Wire(_message(
        "anthropic/claude-sonnet-5.5", usage_extra=plain)).http_client()).complete(
            "S", [USER], [])
    assert _rows(session)[0].reported_cost_usd == pytest.approx(0.0031)


# --- 8. the limit fails closed when today's spend can't be read ---------------------------


def test_budget_read_failure_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "daily_budget_usd", 1.0)

    def broken():
        raise RuntimeError("no such column: llmusage.reported_cost_usd")

    monkeypatch.setattr(usage, "spent_today_usd", broken)
    with pytest.raises(usage.BudgetUnreadableError) as caught:
        usage.check_budget("claude-sonnet-5-5")
    failure = describe_llm_error(caught.value)
    assert (failure.category, failure.status_code) == ("budget", 429)
    assert "could not be read" in failure.detail
    assert "uv run alembic upgrade head" in failure.detail


def test_budget_read_failure_without_a_limit_is_irrelevant(monkeypatch):
    monkeypatch.setattr(settings, "daily_budget_usd", None)
    monkeypatch.setattr(usage, "spent_today_usd", lambda: 1 / 0)
    usage.check_budget("claude-sonnet-5-5")  # no limit: nothing to read, nothing refused


def test_db_revision_problem_names_the_fix(tmp_path):
    import os
    import subprocess
    import sys

    from sqlalchemy import create_engine

    from adaptive_academy.db import db_revision_problem

    url = f"sqlite:///{tmp_path / 'behind.db'}"
    env = {**os.environ, "AA_DATABASE_URL": url}
    root = __import__("pathlib").Path(__file__).resolve().parents[1]
    run = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "b4e8d2f6a3c9"],
                         cwd=root, env=env, capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    engine = create_engine(url)
    problem = db_revision_problem(engine)
    assert problem and "b4e8d2f6a3c9" in problem and "uv run alembic upgrade head" in problem
    run = subprocess.run([sys.executable, "-m", "alembic", "upgrade", "head"],
                         cwd=root, env=env, capture_output=True, text=True, check=False)
    assert run.returncode == 0, run.stderr
    assert db_revision_problem(engine) is None
    engine.dispose()


def test_db_revision_problem_never_raises(tmp_path):
    from sqlalchemy import create_engine

    from adaptive_academy.db import db_revision_problem

    engine = create_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    assert db_revision_problem(engine) is None  # no migration record: not flagged
    assert db_revision_problem(engine, script_dir=tmp_path / "missing") is None


# --- 3. the Anthropic backend never sends its key to openrouter.ai --------------------------


@pytest.mark.parametrize("url", ["https://openrouter.ai/api", "https://openrouter.ai/api/",
                                 "https://OpenRouter.ai", "http://eu.openrouter.ai/api"])
def test_anthropic_backend_ignores_an_openrouter_base_url(session, monkeypatch, url):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", url)  # OpenRouter's own Claude Code setup
    monkeypatch.setattr(settings, "reasoning_model", "")
    wire = Wire(_message("claude-sonnet-5-5"))
    AnthropicLLMClient(http_client=wire.http_client()).complete("S", [USER], [])
    [request] = wire.requests
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == ANTHROPIC_KEY


def test_anthropic_backend_still_honours_a_proxy(session, monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://gateway.example.com/anthropic")
    monkeypatch.setattr(settings, "reasoning_model", "")
    wire = Wire(_message("claude-sonnet-5-5"))
    AnthropicLLMClient(http_client=wire.http_client()).complete("S", [USER], [])
    assert str(wire.requests[0].url) == "https://gateway.example.com/anthropic/v1/messages"


def test_anthropic_base_url_rules(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    assert anthropic_base_url() == "https://api.anthropic.com"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://notopenrouter.ai.example.com")
    assert anthropic_base_url() == "https://notopenrouter.ai.example.com"
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://evil-openrouter.ai")
    assert anthropic_base_url() == "https://evil-openrouter.ai"  # a different host
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.openrouter.ai/x")
    assert anthropic_base_url() == "https://api.anthropic.com"


# --- 4. agent_sdk in the container is refused, legibly, without using an API key ------------


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def agent_sdk_in_container(monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "agent_sdk")
    monkeypatch.setenv("AA_IN_CONTAINER", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)

    class _NoClient:
        def __init__(self, *a, **kw):
            raise AssertionError("no client may be built: agent_sdk can't run here")

    for module in ("anthropic_client", "anthropic_researcher"):
        monkeypatch.setattr(f"adaptive_academy.llm.{module}.Anthropic", _NoClient)
    monkeypatch.setattr("adaptive_academy.llm.agent_sdk_client.AgentSDKLLMClient", _NoClient)


def test_setup_reports_agent_sdk_unusable_in_the_container(client, agent_sdk_in_container):
    body = client.get("/api/setup").json()
    assert body["llm_backend"] == "agent_sdk"
    assert body["llm_ready"] is False
    assert "this container" in body["message"] and "AA_LLM_BACKEND" in body["message"]
    assert "just up" in body["message"]


def test_llm_routes_in_the_container_refuse_agent_sdk_with_a_503(client, session,
                                                                 agent_sdk_in_container):
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    r = client.post(f"/api/concepts/{concept.id}/assess",
                    json={"kind": "self_explanation", "response": "..."})
    assert r.status_code == 503
    assert "this container" in r.json()["detail"]
    r = client.post(f"/api/topics/{topic.id}/research")
    assert r.status_code == 503


def test_agent_sdk_on_the_host_is_unaffected(client, monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "agent_sdk")
    monkeypatch.delenv("AA_IN_CONTAINER", raising=False)
    assert client.get("/api/setup").json()["llm_ready"] is True


def test_startup_names_the_container_problem(agent_sdk_in_container):
    assert any("this container" in p for p in setup_problems())


def test_dockerfile_marks_the_container():
    from pathlib import Path

    dockerfile = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()
    assert "AA_IN_CONTAINER=1" in dockerfile


# --- 5. model catalog ---------------------------------------------------------------------


@pytest.mark.parametrize("model", ["~anthropic/claude-sonnet-latest",
                                   "~anthropic/claude-opus-latest"])
def test_tilde_aliases_are_claude(model):
    assert model_catalog.family_of(model) == "anthropic"
    assert not model_catalog.is_experimental(model)


@pytest.mark.parametrize("model", ["claude-3-5-sonnet-20241022", "anthropic/claude-3.5-sonnet",
                                   "claude-sonnet-4", "claude-opus-4-1",
                                   "anthropic/claude-opus-4.1:beta", "claude-3-haiku-20240307"])
def test_claude_before_4_5_has_no_strict_tools(model):
    caps = model_catalog.capabilities(model)
    assert caps.family == "anthropic-legacy"
    assert not caps.strict_tools and not caps.experimental
    assert caps.anthropic_web_search and caps.thinking_replay


@pytest.mark.parametrize("model", ["claude-haiku-4-5-20251001", "claude-sonnet-4-6",
                                   "anthropic/claude-sonnet-4.5", "claude-sonnet-5-5"])
def test_claude_4_5_and_later_keep_strict_tools(model):
    assert model_catalog.capabilities(model).strict_tools


def test_legacy_claude_structured_output_is_not_strict(session, monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.setattr(settings, "reasoning_model", "claude-sonnet-4-0")
    monkeypatch.setattr(settings, "daily_budget_usd", None)
    wire = Wire(_message("claude-sonnet-4-0", content=[
        {"type": "tool_use", "id": "toolu_1", "name": "emit", "input": {"score": 1}}],
        stop_reason="tool_use"))
    out = AnthropicLLMClient(http_client=wire.http_client()).complete_json(
        "S", [USER], schema={"type": "object", "properties": {"score": {"type": "number"}},
                             "required": ["score"]}, tool_name="emit")
    assert out == {"score": 1}
    [tool] = json.loads(wire.requests[0].content)["tools"]
    assert "strict" not in tool
    assert json.loads(wire.requests[0].content)["tool_choice"]["type"] == "auto"


def test_bare_model_id_on_openrouter_gets_a_setup_warning(client, openrouter, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_model", "claude-sonnet-5-5")
    body = client.get("/api/setup").json()
    [warning] = body["setup_warnings"]
    assert "AA_MODEL_REASONING" in warning and "'claude-sonnet-5-5'" in warning
    assert "anthropic/claude-sonnet-5.5" in warning
    monkeypatch.setattr(settings, "reasoning_model", "~anthropic/claude-sonnet-latest")
    assert client.get("/api/setup").json()["setup_warnings"] == []


def test_bare_model_id_is_fine_on_the_anthropic_backend(client, monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    assert client.get("/api/setup").json()["setup_warnings"] == []


# --- 6. a key in the wrong variable --------------------------------------------------------


def test_anthropic_key_in_the_openrouter_variable(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", ANTHROPIC_KEY)
    problem = key_problem(OPENROUTER)
    assert "OPENROUTER_API_KEY holds an Anthropic key" in problem
    assert ANTHROPIC_KEY not in problem
    with pytest.raises(MissingAPIKeyError, match="OPENROUTER_API_KEY"):
        require_api_key(OPENROUTER)


def test_openrouter_key_in_the_anthropic_variable(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", OPENROUTER_KEY)
    problem = key_problem(ANTHROPIC)
    assert "ANTHROPIC_API_KEY holds an OpenRouter key" in problem
    assert OPENROUTER_KEY not in problem


def test_setup_explains_a_key_in_the_wrong_variable(client, openrouter, monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", ANTHROPIC_KEY)
    r = client.get("/api/setup")
    body = r.json()
    assert body["llm_ready"] is False and body["missing_key"] == "OPENROUTER_API_KEY"
    assert "holds an Anthropic key" in body["key_hint"]
    assert ANTHROPIC_KEY not in r.text
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert client.get("/api/setup").json()["key_hint"] is None  # simply missing


# --- 7. a mistyped AA_LLM_BACKEND ----------------------------------------------------------


def test_mistyped_backend_is_named_in_setup_and_at_startup(client, monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "openroutr")
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    body = client.get("/api/setup").json()
    assert body["llm_backend"] == "anthropic"
    [warning] = body["setup_warnings"]
    assert "'openroutr'" in warning
    for value in ("anthropic", "openrouter", "agent_sdk"):
        assert value in warning
    assert any("'openroutr'" in p for p in setup_problems())


# --- errors: OpenRouter wording only on OpenRouter -------------------------------------------


def test_routing_wording_is_openrouter_only(monkeypatch):
    import anthropic

    exc = anthropic.InternalServerError(
        "x", response=httpx.Response(503, request=httpx.Request("POST", "https://h/v1/messages")),
        body={"error": {"message": "no available model provider that meets your routing "
                                   "requirements"}})
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    assert describe_llm_error(exc).category == "overloaded"
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    failure = describe_llm_error(exc)
    assert failure.category == "model_unavailable"
    assert "train on your prompts" in failure.detail


# --- 9. the fixture recorder refuses a non-Anthropic backend --------------------------------


def test_fixture_recorder_refuses_other_backends(monkeypatch, capsys, tmp_path):
    import importlib.util
    import sys
    from pathlib import Path

    path = Path(__file__).resolve().parents[1] / "scripts" / "record_response_fixtures.py"
    spec = importlib.util.spec_from_file_location("record_response_fixtures_or", path)
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, spec.name, module)
    spec.loader.exec_module(module)
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    assert module.main(["--live", "--yes", "--out", str(tmp_path)]) == 2
    assert "Unset AA_LLM_BACKEND" in capsys.readouterr().err
    assert list(tmp_path.iterdir()) == []
