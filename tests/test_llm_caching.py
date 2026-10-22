"""Prompt caching on the API-key clients, and the cache-read share on GET /api/usage.

From the claude-api skill (shared/prompt-caching.md): render order is tools -> system ->
messages, and a breakpoint on the last stable system block caches tools + system together.
Top-level `cache_control` (automatic caching) puts one breakpoint on the last cacheable block
and moves it forward as a conversation grows. A prefix under the model's minimum (512 tokens
on the 5.5 models) silently isn't cached; that is a no-op, not an error, so the markers are
sent regardless. Single-shot calls get no automatic breakpoint: it would land on the unique
user message and pay the write premium on bytes nobody reads back.
"""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from adaptive_academy.api.app import app
from adaptive_academy.api.deps import get_session
from adaptive_academy.llm import today
from adaptive_academy.llm.researcher_types import SearchBrief
from adaptive_academy.models import LLMUsage

EPHEMERAL = {"type": "ephemeral"}


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    monkeypatch.setattr(today, "local_now", lambda: datetime(2026, 10, 22, tzinfo=timezone.utc))


def _fake_anthropic(monkeypatch, module, responses, calls):
    queue = list(responses)

    class _Messages:
        def create(self, **kw):
            calls.append(kw)
            return queue.pop(0)

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr(f"adaptive_academy.llm.{module}.Anthropic", _FakeAnthropic)


def _resp(*blocks, stop_reason="end_turn"):
    usage = SimpleNamespace(input_tokens=1, output_tokens=1, cache_creation_input_tokens=0,
                            cache_read_input_tokens=0, server_tool_use=None)
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage)


def _text(t):
    return SimpleNamespace(type="text", text=t)


def _assert_stable_system_breakpoint(kw, stable_prefix: str):
    """System = [stable text with the breakpoint, then today's date with none]."""
    stable, dated = kw["system"]
    assert stable["type"] == "text" and stable["text"].startswith(stable_prefix)
    assert stable["cache_control"] == EPHEMERAL
    assert dated["text"] == today.today_line()
    assert "cache_control" not in dated
    # Nothing else carries a marker: tools are cached through the system breakpoint.
    assert all("cache_control" not in t for t in kw.get("tools", []))


TOOL = {"name": "log_attempt", "description": "d",
        "input_schema": {"type": "object", "properties": {}}}


def test_single_shot_complete_caches_only_the_stable_prefix(api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", [_resp(_text("ok"))], calls)
    AnthropicLLMClient().complete("SYS", [{"role": "user", "content": "x"}], [])
    [kw] = calls
    _assert_stable_system_breakpoint(kw, "SYS")
    assert "cache_control" not in kw  # no automatic breakpoint on a one-off message


def test_tool_conversation_also_caches_the_growing_conversation(api_key, monkeypatch):
    # The tutor: tools + a conversation that grows every step and every turn. Automatic
    # caching moves the breakpoint to the end each request, so the next one reads it.
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", [_resp(_text("ok"))], calls)
    AnthropicLLMClient().complete("TUTOR", [{"role": "user", "content": "x"}], [TOOL])
    [kw] = calls
    _assert_stable_system_breakpoint(kw, "TUTOR")
    assert kw["cache_control"] == EPHEMERAL


def test_multi_turn_without_tools_caches_the_conversation(api_key, monkeypatch):
    # e.g. the roleplay persona: a history but no tools.
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    history = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"},
               {"role": "user", "content": "c"}]
    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", [_resp(_text("ok"))], calls)
    AnthropicLLMClient().complete("PERSONA", history, [])
    assert calls[0]["cache_control"] == EPHEMERAL
    assert calls[0]["messages"] == history  # markers never edit the caller's history


def test_complete_json_caches_tools_and_system_on_both_attempts(api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    tool_use = SimpleNamespace(type="tool_use", id="t", name="emit", input={"a": "b"})
    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client",
                    [_resp(_text("prose")), _resp(tool_use, stop_reason="tool_use")], calls)
    AnthropicLLMClient().complete_json(
        "SYS", [{"role": "user", "content": "x"}],
        schema={"type": "object", "properties": {"a": {"type": "string"}}}, tool_name="emit")
    first, retry = calls
    _assert_stable_system_breakpoint(first, "SYS")
    assert "cache_control" not in first
    # The corrective retry re-sends the identical tools + system, so it reads that prefix.
    assert retry["system"] == first["system"] and retry["tools"] == first["tools"]


def test_researcher_caches_prefix_and_its_pause_turn_continuations(api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
    from adaptive_academy.prompts import RESEARCH_SEARCH

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_researcher",
                    [_resp(_text("Searching."), stop_reason="pause_turn"), _resp(_text("[]"))],
                    calls)
    AnthropicResearcherClient().search(SearchBrief(angle="a", query="q"))
    for kw in calls:
        _assert_stable_system_breakpoint(kw, RESEARCH_SEARCH)
        # Search results are large; a continuation re-sends them, so it should read them.
        assert kw["cache_control"] == EPHEMERAL
    assert calls[1]["system"] == calls[0]["system"]


def test_breakpoint_count_stays_within_the_api_limit(api_key, monkeypatch):
    # Max 4 cache_control breakpoints per request; the automatic one takes a slot too.
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", [_resp(_text("ok"))], calls)
    AnthropicLLMClient().complete("S", [{"role": "user", "content": "x"}], [TOOL])
    kw = calls[0]
    explicit = str(kw["system"]).count("cache_control") + str(kw["messages"]).count(
        "cache_control") + str(kw["tools"]).count("cache_control")
    assert explicit + (1 if "cache_control" in kw else 0) <= 4


# --- cache-read share per feature (GET /api/usage) -------------------------------------


def _row(session, feature, *, inp, write=0, read=0):
    session.add(LLMUsage(backend="anthropic", model="claude-sonnet-5-5", role="reasoning",
                         operation="complete", feature=feature, input_tokens=inp,
                         output_tokens=5, cache_creation_input_tokens=write,
                         cache_read_input_tokens=read, cost_usd=0.01))
    session.commit()


def test_usage_reports_the_cache_read_share_per_feature(session):
    _row(session, "tutor", inp=100, write=100, read=600)
    _row(session, "tutor", inp=100, write=0, read=100)
    _row(session, "research", inp=500)
    app.dependency_overrides[get_session] = lambda: session
    try:
        body = TestClient(app).get("/api/usage").json()
    finally:
        app.dependency_overrides.clear()
    by = {f["feature"]: f for f in body["by_feature"]}
    # Share of all input tokens (uncached + cache writes + cache reads) read from cache.
    assert by["tutor"]["cache_read_share"] == pytest.approx(700 / 1000)
    assert by["research"]["cache_read_share"] == 0.0


def test_cache_read_share_is_null_without_input_tokens():
    from adaptive_academy.llm.usage import cache_read_share

    assert cache_read_share({"input_tokens": 0, "cache_creation_input_tokens": 0,
                             "cache_read_input_tokens": 0}) is None
    assert cache_read_share({"input_tokens": 1, "cache_creation_input_tokens": 1,
                             "cache_read_input_tokens": 2}) == 0.5
