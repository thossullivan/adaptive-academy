import os

import pytest

import adaptive_academy.llm.agent_sdk_client as mod
from adaptive_academy.llm.agent_sdk_client import AgentSDKLLMClient, flatten_messages


def test_create_app_drops_api_key_only_in_agent_sdk_mode(monkeypatch):
    from adaptive_academy.api.app import create_app

    # agent_sdk mode: key dropped process-wide so all SDK subprocesses use the subscription.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
    monkeypatch.setenv("AA_LLM_BACKEND", "agent_sdk")
    create_app()
    assert "ANTHROPIC_API_KEY" not in os.environ

    # Default mode: key untouched.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-y")
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    create_app()
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-y"


def test_flatten_single_passthrough_and_multi_roleprefix():
    assert flatten_messages([{"role": "user", "content": "hi"}]) == "hi"
    out = flatten_messages([{"role": "user", "content": "a"}, {"role": "tutor", "content": "b"}])
    assert "USER: a" in out and "TUTOR: b" in out


def test_complete_with_tools_no_key_raises_legible_error(monkeypatch):
    # Pure-subscription user (no key) + a tool-use turn must raise a legible AgentSDKError
    # (-> 502), not a bare KeyError 500 from AnthropicLLMClient construction.
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(mod.AgentSDKError):
        AgentSDKLLMClient(role="reasoning").complete(
            "sys", [{"role": "user", "content": "x"}], tools=[{"name": "reveal"}])


def test_complete_with_tools_bridges_to_api_key_client(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")
    # Tool-use turns aren't ported yet — they must transparently use the API-key client
    # so the Tutor keeps working in agent_sdk mode.
    seen = {}

    class _FakeAnthropic:
        def __init__(self, role):
            seen["role"] = role

        def complete(self, system, messages, tools):
            seen["tools"] = tools
            return mod.LLMResponse(text="from-api-key", tool_calls=[])

    monkeypatch.setattr("adaptive_academy.llm.anthropic_client.AnthropicLLMClient", _FakeAnthropic)
    resp = AgentSDKLLMClient(role="reasoning").complete(
        "sys", [{"role": "user", "content": "x"}], tools=[{"name": "reveal"}])
    assert resp.text == "from-api-key"
    assert seen["role"] == "reasoning" and seen["tools"] == [{"name": "reveal"}]


class _FakeResult:
    def __init__(self, result, is_error=False):
        self.result = result
        self.is_error = is_error


def test_complete_no_tools_returns_query_text(monkeypatch):
    # agent_sdk mode drops the key process-wide (create_app), so the client just queries —
    # no per-call strip, no lock.
    async def fake_query(prompt, options):
        assert prompt == "explain softmax"
        yield _FakeResult("graded text")

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)

    resp = AgentSDKLLMClient(role="reasoning").complete(
        "sys", [{"role": "user", "content": "explain softmax"}], tools=[])
    assert resp.text == "graded text"
    assert resp.tool_calls == []


def test_complete_raises_on_error_result(monkeypatch):
    async def fake_query(prompt, options):
        yield _FakeResult("Invalid API key", is_error=True)

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)

    with pytest.raises(mod.AgentSDKError):
        AgentSDKLLMClient(role="reasoning").complete(
            "s", [{"role": "user", "content": "x"}], tools=[])
