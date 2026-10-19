import anthropic
import httpx
from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.llm.scripted_client import ScriptedLLMClient
from adaptive_academy.llm.types import LLMResponse
from adaptive_academy.models import Concept, Topic, Track


class _AuthBoomLLM:
    """An LLMClient whose every call fails like a rejected API key."""

    def complete(self, system, messages, tools):
        raise anthropic.AuthenticationError(
            "invalid x-api-key",
            response=httpx.Response(
                401, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
            body=None)


class _OverloadBoomLLM:
    def complete(self, system, messages, tools):
        raise anthropic.InternalServerError(
            "overloaded",
            response=httpx.Response(
                529, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
            body=None)


class _BillingBoomLLM:
    def complete(self, system, messages, tools):
        raise anthropic.BadRequestError(
            "Your credit balance is too low to access the Anthropic API.",
            response=httpx.Response(
                400, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
            body=None)


SECRET = "sk-ant-api03-SUPERSECRETVALUE-do-not-leak"


def _not_found(message: str, body=None) -> anthropic.NotFoundError:
    """What the API returns for an unknown/retired model id: 404 not_found_error."""
    return anthropic.NotFoundError(
        message,
        response=httpx.Response(
            404, request=httpx.Request("POST", "https://api.anthropic.com/v1/messages")),
        body=body)


class _RaisingLLM:
    def __init__(self, exc):
        self._exc = exc

    def complete(self, system, messages, tools):
        raise self._exc


def _seed_concept(session):
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


def test_llm_auth_error_returns_clean_502(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: _AuthBoomLLM()
    cid = _seed_concept(session)
    r = TestClient(app).post(f"/api/concepts/{cid}/assess",
                             json={"kind": "self_explanation", "response": "..."})
    assert r.status_code == 502
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]
    app.dependency_overrides.clear()


def test_llm_upstream_error_returns_clean_502(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: _OverloadBoomLLM()
    cid = _seed_concept(session)
    r = TestClient(app).post(f"/api/concepts/{cid}/assess",
                             json={"kind": "self_explanation", "response": "..."})
    assert r.status_code == 502
    assert "detail" in r.json()
    app.dependency_overrides.clear()


def test_upstream_error_surfaces_actionable_message(session):
    # A vague "(BadRequestError)" hid "credit balance too low" during a live run.
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: _BillingBoomLLM()
    cid = _seed_concept(session)
    r = TestClient(app).post(f"/api/concepts/{cid}/assess",
                             json={"kind": "self_explanation", "response": "..."})
    assert r.status_code == 502
    assert "credit balance is too low" in r.json()["detail"]
    app.dependency_overrides.clear()


def test_agent_sdk_error_returns_clean_502(session):
    # A subscription-backend failure must be a legible 502, not a bare 500.
    from adaptive_academy.llm.types import AgentSDKError

    class _AgentBoomLLM:
        def complete(self, system, messages, tools):
            raise AgentSDKError("subscription usage limit reached")

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: _AgentBoomLLM()
    cid = _seed_concept(session)
    r = TestClient(app).post(f"/api/concepts/{cid}/assess",
                             json={"kind": "self_explanation", "response": "..."})
    assert r.status_code == 502
    assert "subscription usage limit reached" in r.json()["detail"]
    app.dependency_overrides.clear()


def test_malformed_or_truncated_llm_json_returns_clean_502(session):
    # The live failure mode: the model returns JSON our parser can't load
    # (e.g. truncated at max_tokens). Must be a legible 502, not a bare 500.
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: ScriptedLLMClient(
        [LLMResponse(text='{"criteria": ["a", "b"')])  # truncated mid-array
    cid = _seed_concept(session)
    r = TestClient(app).post(f"/api/concepts/{cid}/assess",
                             json={"kind": "self_explanation", "response": "x"})
    assert r.status_code == 502
    assert "detail" in r.json()
    app.dependency_overrides.clear()


def test_anthropic_client_token_budget_is_generous(monkeypatch):
    # 1024 truncated structured outputs live; the budget must be large enough that
    # rubric/curriculum/anchor JSON doesn't get cut off mid-structure.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
    assert AnthropicLLMClient()._max_tokens >= 4096
    assert AnthropicLLMClient(max_tokens=10)._max_tokens == 10


def _assess_with(session, llm):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: llm
    try:
        cid = _seed_concept(session)
        return TestClient(app).post(f"/api/concepts/{cid}/assess",
                                    json={"kind": "self_explanation", "response": "..."})
    finally:
        app.dependency_overrides.clear()


def test_unknown_reasoning_model_names_the_setting_to_change(session, monkeypatch):
    # A retired/unknown model id comes back as 404 not_found_error; the user needs to know
    # which setting to change, not "(NotFoundError) model: …".
    from adaptive_academy.settings import settings

    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    monkeypatch.setattr(settings, "reasoning_model", "claude-retired-9")
    body = {"type": "error",
            "error": {"type": "not_found_error", "message": "model: claude-retired-9"}}
    exc = _not_found(f"Error code: 404 - {body}", body=body)
    r = _assess_with(session, _RaisingLLM(exc))
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "'claude-retired-9'" in detail
    assert "not available to this API key" in detail
    assert "AA_MODEL_REASONING" in detail
    assert "AA_MODEL_COPY" not in detail  # the id matched the reasoning role only
    assert ".env" in detail and "restart the API" in detail
    assert SECRET not in r.text and "SUPERSECRET" not in r.text


def test_unknown_copy_model_names_the_copy_setting(session, monkeypatch):
    from adaptive_academy.settings import settings

    monkeypatch.setattr(settings, "copy_model", "claude-haiku-old")
    r = _assess_with(session, _RaisingLLM(_not_found("model: claude-haiku-old")))
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "'claude-haiku-old'" in detail
    assert "AA_MODEL_COPY" in detail
    assert "AA_MODEL_REASONING" not in detail


def test_not_found_for_an_unconfigured_model_id_names_both_settings(session):
    r = _assess_with(session, _RaisingLLM(_not_found("model: claude-somewhere-else")))
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "'claude-somewhere-else'" in detail
    assert "AA_MODEL_REASONING" in detail and "AA_MODEL_COPY" in detail


def test_not_found_without_model_id_names_both_settings(session, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", SECRET)
    r = _assess_with(session, _RaisingLLM(_not_found("Not Found")))
    assert r.status_code == 502
    detail = r.json()["detail"]
    assert "AA_MODEL_REASONING" in detail and "AA_MODEL_COPY" in detail
    assert "not available to this API key" in detail
    assert SECRET not in r.text


def test_not_found_never_echoes_text_beyond_the_model_id(session):
    # Only a model-id-shaped token is lifted from the upstream message; nothing else is echoed.
    exc = _not_found(f"model: claude-x key={SECRET} trailing")
    r = _assess_with(session, _RaisingLLM(exc))
    assert r.status_code == 502
    assert "'claude-x'" in r.json()["detail"]
    assert SECRET not in r.text and "SUPERSECRET" not in r.text and "trailing" not in r.text
