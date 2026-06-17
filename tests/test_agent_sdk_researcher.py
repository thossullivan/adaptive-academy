import json

import pytest

import adaptive_academy.llm.agent_sdk_researcher as mod
from adaptive_academy.llm.agent_sdk_researcher import AgentSDKResearcherClient
from adaptive_academy.llm.researcher_types import SearchBrief


class _FakeResult:
    def __init__(self, result, is_error=False):
        self.result = result
        self.is_error = is_error


def test_search_parses_sources_and_stamps_angle(monkeypatch):
    payload = json.dumps([
        {"title": "RAG paper", "url": "https://arxiv.org/abs/2005.11401", "tier": 1,
         "summary": "s", "why": "w", "relevance": 0.9}])

    async def fake_query(prompt, options):
        assert prompt == "find RAG papers"
        # WebSearch must be the only exposed tool, with permissions bypassed.
        assert options.allowed_tools == ["WebSearch"]
        assert options.permission_mode == "bypassPermissions"
        yield _FakeResult(payload)

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)

    out = AgentSDKResearcherClient().search(
        SearchBrief(angle="foundational_papers", query="find RAG papers"))
    assert len(out) == 1
    assert out[0].url == "https://arxiv.org/abs/2005.11401"
    assert out[0].angle == "foundational_papers"  # stamped by the client


def test_search_raises_on_error_result(monkeypatch):
    async def fake_query(prompt, options):
        yield _FakeResult("usage limit", is_error=True)

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)

    with pytest.raises(mod.AgentSDKError):
        AgentSDKResearcherClient().search(SearchBrief(angle="x", query="q"))


def test_search_degrades_to_empty_on_unparseable(monkeypatch):
    async def fake_query(prompt, options):
        yield _FakeResult("not json at all")

    monkeypatch.setattr(mod, "ResultMessage", _FakeResult)
    monkeypatch.setattr(mod, "query", fake_query)

    assert AgentSDKResearcherClient().search(SearchBrief(angle="x", query="q")) == []
