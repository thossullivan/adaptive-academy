import os

import pytest

import adaptive_academy.llm.agent_sdk_client as mod
from adaptive_academy.llm.agent_sdk_client import AgentSDKLLMClient, flatten_messages


def test_flatten_single_passthrough_and_multi_roleprefix():
    assert flatten_messages([{"role": "user", "content": "hi"}]) == "hi"
    out = flatten_messages([{"role": "user", "content": "a"}, {"role": "tutor", "content": "b"}])
    assert "USER: a" in out and "TUTOR: b" in out


def test_complete_with_tools_bridges_to_api_key_client(monkeypatch):
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


def test_complete_strips_key_during_call_and_restores_after(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")

    async def fake_query(prompt, options):
        # The whole point: the subprocess must NOT see the API key (-> subscription auth).
        assert "ANTHROPIC_API_KEY" not in os.environ
        assert prompt == "explain softmax"
        yield _FakeResult("graded text")

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)

    resp = AgentSDKLLMClient(role="reasoning").complete(
        "sys", [{"role": "user", "content": "explain softmax"}], tools=[])
    assert resp.text == "graded text"
    assert resp.tool_calls == []
    # Restored for the still-API-key Researcher/Anchor clients.
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-real"


def test_complete_raises_on_error_result(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real")

    async def fake_query(prompt, options):
        yield _FakeResult("Invalid API key", is_error=True)

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)

    with pytest.raises(mod.AgentSDKError):
        AgentSDKLLMClient(role="reasoning").complete(
            "s", [{"role": "user", "content": "x"}], tools=[])
    # Even on error, the key is restored.
    assert os.environ["ANTHROPIC_API_KEY"] == "sk-real"
