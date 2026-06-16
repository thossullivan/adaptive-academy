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
