"""First-run legibility: /api/setup reports LLM readiness, and a missing key is a legible 503."""

import pytest
from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.models import Concept, Topic, Track

SECRET = "sk-ant-api03-SUPERSECRETVALUE-do-not-leak"


@pytest.fixture
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def no_network(monkeypatch):
    """Fail loudly if anything tries to build a real Anthropic SDK client."""

    class _NoNetwork:
        def __init__(self, *a, **kw):
            raise AssertionError("a real Anthropic client was constructed")

    monkeypatch.setattr("adaptive_academy.llm.anthropic_client.Anthropic", _NoNetwork)
    monkeypatch.setattr("adaptive_academy.llm.anthropic_researcher.Anthropic", _NoNetwork)


def test_setup_ready_when_key_set(client, monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    r = client.get("/api/setup")
    assert r.status_code == 200
    body = r.json()
    assert body["llm_backend"] == "anthropic"
    assert body["llm_ready"] is True
    assert isinstance(body["message"], str) and body["message"]
    # Neither the key nor any recognisable fragment of it is ever echoed back.
    assert SECRET not in r.text
    assert "SUPERSECRET" not in r.text
    assert SECRET[-6:] not in r.text


@pytest.mark.parametrize("value", [None, "", "   "])
def test_setup_not_ready_when_key_unset_or_blank(client, monkeypatch, value):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    if value is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", value)
    body = client.get("/api/setup").json()
    assert body["llm_backend"] == "anthropic"
    assert body["llm_ready"] is False
    assert "ANTHROPIC_API_KEY" in body["message"]


@pytest.mark.parametrize("placeholder", ["sk-ant-xxxxx", "sk-ant-...", "sk-ant-…"])
def test_setup_not_ready_when_key_is_a_documented_placeholder(client, monkeypatch, placeholder):
    # Copying .env.example unedited, or pasting the README/notice example literally, is the
    # commonest first-run slip.
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", placeholder)
    r = client.get("/api/setup")
    body = r.json()
    assert body["llm_ready"] is False
    assert placeholder not in r.text


def test_setup_ready_in_agent_sdk_mode_without_key(client, monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "agent_sdk")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    body = client.get("/api/setup").json()
    assert body["llm_backend"] == "agent_sdk"
    assert body["llm_ready"] is True


def test_agent_sdk_tutor_turn_runs_without_key(client, session, monkeypatch, no_network):
    # agent_sdk reports llm_ready with no key, so the Tutor must actually work then: its
    # tool turn goes through the SDK tutor (in-process tools), never the raising key bridge.
    import adaptive_academy.engine.tutor_sdk as tutor_sdk
    from adaptive_academy.llm.agent_sdk_client import AgentSDKLLMClient

    monkeypatch.setenv("AA_LLM_BACKEND", "agent_sdk")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    class _Result:
        def __init__(self, result):
            self.result = result
            self.is_error = False

    async def fake_query(prompt, options):
        assert "mcp__tutor__reveal_solution" in options.allowed_tools
        yield _Result("Try writing the softmax denominator first.")

    def bridge(*a, **kw):
        raise AssertionError("agent_sdk Tutor turn used the API-key bridge")

    monkeypatch.setattr(tutor_sdk, "ResultMessage", _Result)
    monkeypatch.setattr(tutor_sdk, "query", fake_query)
    monkeypatch.setattr(AgentSDKLLMClient, "complete", bridge)

    cid = _seed_concept(session)
    topic_id = session.get(Track, session.get(Concept, cid).track_id).topic_id
    convo = client.post("/api/conversations", json={"topic_id": topic_id, "concept_id": cid})
    assert convo.status_code == 200
    r = client.post(f"/api/conversations/{convo.json()['id']}/messages",
                    json={"content": "how does softmax work?"})
    assert r.status_code == 200
    assert r.json()["reply"] == "Try writing the softmax denominator first."


def _seed_concept(session) -> int:
    topic = Topic(title="T")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="tr")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="softmax")
    session.add(concept)
    session.commit()
    return concept.id


@pytest.mark.parametrize("value", [None, "", "  "])
def test_llm_route_without_key_is_legible_503(client, session, monkeypatch, no_network, value):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    if value is None:
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    else:
        monkeypatch.setenv("ANTHROPIC_API_KEY", value)
    cid = _seed_concept(session)
    r = client.post(f"/api/concepts/{cid}/assess",
                    json={"kind": "self_explanation", "response": "..."})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert "No ANTHROPIC_API_KEY is set" in detail
    assert ".env.example" in detail
    assert "just api" in detail


def test_research_route_without_key_is_legible_503(client, session, monkeypatch, no_network):
    # The Researcher client is built separately from the LLM client — cover it too.
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    topic = Topic(title="T", goal="g")
    session.add(topic)
    session.commit()
    r = client.post(f"/api/topics/{topic.id}/research")
    assert r.status_code == 503
    assert "No ANTHROPIC_API_KEY is set" in r.json()["detail"]


def test_anthropic_clients_raise_typed_error_without_key(monkeypatch, no_network):
    from adaptive_academy.llm.anthropic_anchor import AnthropicAnchorClient
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
    from adaptive_academy.llm.keys import MissingAPIKeyError

    monkeypatch.setenv("ANTHROPIC_API_KEY", " ")
    for ctor in (AnthropicLLMClient, AnthropicResearcherClient, AnthropicAnchorClient):
        with pytest.raises(MissingAPIKeyError):
            ctor()


def test_setup_reports_resolved_models(client, monkeypatch):
    from adaptive_academy.settings import settings

    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr(settings, "reasoning_model", "claude-opus-5-5")
    monkeypatch.setattr(settings, "copy_model", "  ")  # blank → default
    r = client.get("/api/setup")
    assert r.status_code == 200
    assert r.json()["models"] == {"reasoning": "claude-opus-5-5", "copy": "claude-haiku-5-5"}
    assert SECRET not in r.text


def test_setup_warns_when_the_limit_cannot_cap_an_unpriced_model(client, monkeypatch):
    from adaptive_academy.settings import settings

    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr(settings, "daily_budget_usd", 5.0)
    monkeypatch.setattr(settings, "reasoning_model", "claude-unpriced-test")
    monkeypatch.setattr(settings, "copy_model", "claude-haiku-5-5")
    warnings = client.get("/api/setup").json()["warnings"]
    assert len(warnings) == 1
    assert "claude-unpriced-test" in warnings[0] and "AA_DAILY_BUDGET_USD" in warnings[0]


def test_setup_has_no_warnings_by_default(client, monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    assert client.get("/api/setup").json()["warnings"] == []


def test_setup_has_no_budget_warning_in_agent_sdk_mode(client, monkeypatch):
    # Subscription calls are never capped, so an unpriced model there is not a budget hole.
    from adaptive_academy.settings import settings

    monkeypatch.setenv("AA_LLM_BACKEND", "agent_sdk")
    monkeypatch.setattr(settings, "daily_budget_usd", 5.0)
    monkeypatch.setattr(settings, "reasoning_model", "claude-unpriced-test")
    assert client.get("/api/setup").json()["warnings"] == []


def test_setup_reports_models_in_agent_sdk_mode(client, monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "agent_sdk")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    models = client.get("/api/setup").json()["models"]
    assert set(models) == {"reasoning", "copy"}
    assert all(isinstance(v, str) and v for v in models.values())


def test_setup_reports_models_when_key_missing(client, monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    body = client.get("/api/setup").json()
    assert body["llm_ready"] is False
    assert set(body["models"]) == {"reasoning", "copy"}


# --- missing key and experimental models, per backend ------------------------------------

OR_SECRET = "sk-or-v1-SUPERSECRETVALUE-do-not-leak"


@pytest.fixture
def default_models(monkeypatch):
    from adaptive_academy.settings import settings

    monkeypatch.setattr(settings, "reasoning_model", "")
    monkeypatch.setattr(settings, "copy_model", "")


def test_setup_anthropic_reports_its_missing_key(client, monkeypatch, default_models):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    body = client.get("/api/setup").json()
    assert body["missing_key"] == "ANTHROPIC_API_KEY"
    assert body["provider"] == "Anthropic"
    assert body["experimental_models"] == [] and body["experimental_warning"] is None
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    assert client.get("/api/setup").json()["missing_key"] is None


def test_setup_openrouter_ready(client, monkeypatch, default_models):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", OR_SECRET)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)  # not needed on this backend
    r = client.get("/api/setup")
    body = r.json()
    assert body["llm_backend"] == "openrouter"
    assert body["provider"] == "OpenRouter"
    assert body["llm_ready"] is True
    assert body["missing_key"] is None
    assert "OpenRouter" in body["message"]
    assert body["models"] == {"reasoning": "anthropic/claude-sonnet-5.5",
                              "copy": "anthropic/claude-haiku-5.5"}
    assert body["experimental_models"] == [] and body["experimental_warning"] is None
    assert OR_SECRET not in r.text and "SUPERSECRET" not in r.text


@pytest.mark.parametrize("value", [None, "", "  ", "sk-or-xxxxx"])
def test_setup_openrouter_names_its_missing_key(client, monkeypatch, default_models, value):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)  # an Anthropic key does not count
    if value is None:
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    else:
        monkeypatch.setenv("OPENROUTER_API_KEY", value)
    r = client.get("/api/setup")
    body = r.json()
    assert body["llm_ready"] is False
    assert body["missing_key"] == "OPENROUTER_API_KEY"
    assert "OPENROUTER_API_KEY" in body["message"]
    assert SECRET not in r.text


def test_setup_warns_about_an_experimental_model(client, monkeypatch, default_models):
    from adaptive_academy.settings import settings

    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", OR_SECRET)
    monkeypatch.setattr(settings, "reasoning_model", "deepseek/deepseek-v4")
    body = client.get("/api/setup").json()
    assert body["experimental_models"] == ["deepseek/deepseek-v4"]
    warning = body["experimental_warning"]
    assert "deepseek/deepseek-v4" in warning and "AA_MODEL_REASONING" in warning
    assert "experimental" in warning.lower()
    assert "—" not in warning
    # OpenRouter reports every call's cost, so an unpriced model is no budget hole there.
    monkeypatch.setattr(settings, "daily_budget_usd", 5.0)
    assert client.get("/api/setup").json()["warnings"] == []


def test_llm_route_on_openrouter_without_key_is_legible_503(client, session, monkeypatch,
                                                            no_network):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    cid = _seed_concept(session)
    r = client.post(f"/api/concepts/{cid}/assess",
                    json={"kind": "self_explanation", "response": "..."})
    assert r.status_code == 503
    assert "No OPENROUTER_API_KEY is set" in r.json()["detail"]
    assert r.json()["category"] == "auth"


# --- grading strictness (AA_GRADING_STRICTNESS) ------------------------------------------

def _strictness_body(client, monkeypatch, raw: str, backend: str | None = None) -> dict:
    from adaptive_academy.settings import settings

    if backend is None:
        monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
        monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    else:
        monkeypatch.setenv("AA_LLM_BACKEND", backend)
    monkeypatch.setattr(settings, "grading_strictness", raw)
    return client.get("/api/setup").json()


def test_setup_reports_standard_strictness_by_default(client, monkeypatch):
    body = _strictness_body(client, monkeypatch, "standard")
    assert body["grading_strictness"] == "standard"
    assert body["setup_warnings"] == []


@pytest.mark.parametrize("backend", [None, "agent_sdk", "openrouter"])
@pytest.mark.parametrize("raw, level", [("strict", "strict"), (" Lenient ", "lenient")])
def test_setup_reports_the_configured_strictness(client, monkeypatch, backend, raw, level):
    if backend == "openrouter":
        monkeypatch.setenv("OPENROUTER_API_KEY", OR_SECRET)
    body = _strictness_body(client, monkeypatch, raw, backend)
    assert body["grading_strictness"] == level
    assert not any("AA_GRADING_STRICTNESS" in w for w in body.get("setup_warnings", []))


@pytest.mark.parametrize("backend", [None, "agent_sdk"])
def test_setup_warns_about_an_unknown_strictness(client, monkeypatch, backend):
    body = _strictness_body(client, monkeypatch, "harsh", backend)
    assert body["grading_strictness"] == "standard"
    (warning,) = [w for w in body["setup_warnings"] if "AA_GRADING_STRICTNESS" in w]
    assert "'harsh'" in warning and "standard" in warning
    assert "—" not in warning


def test_setup_strictness_warning_does_not_echo_a_key(client, monkeypatch):
    r_body = _strictness_body(client, monkeypatch, SECRET)
    assert SECRET not in str(r_body) and "SUPERSECRET" not in str(r_body)
    assert any("AA_GRADING_STRICTNESS" in w for w in r_body["setup_warnings"])
