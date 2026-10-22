"""AA_LLM_BACKEND=openrouter: the same Anthropic SDK clients, pointed at OpenRouter.

Every request here goes through the real SDK to an httpx MockTransport (the `http_client=`
seam), so the headers and body are exactly what would cross the wire. No socket is opened.
"""

import json

import httpx
import pytest
from sqlmodel import select

from adaptive_academy.llm import usage
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
from adaptive_academy.llm.researcher_types import SearchBrief
from adaptive_academy.models import LLMUsage
from adaptive_academy.settings import settings

ANTHROPIC_KEY = "sk-ant-api03-MUST-NOT-REACH-OPENROUTER"
ANTHROPIC_TOKEN = "anthropic-bearer-MUST-NOT-REACH-OPENROUTER"
OPENROUTER_KEY = "sk-or-v1-test-not-a-real-key"
USER = {"role": "user", "content": "What does the learning rate do?"}
SCHEMA = {"type": "object", "properties": {"score": {"type": "number"}}, "required": ["score"]}


def _message(content, *, model="anthropic/claude-sonnet-5.5", stop_reason="end_turn",
             cost=0.0123, searches=None):
    usage_body = {"input_tokens": 100, "output_tokens": 20, "cache_creation_input_tokens": 0,
                  "cache_read_input_tokens": 0}
    if cost is not None:
        usage_body["cost"] = cost
    if searches is not None:
        usage_body["server_tool_use"] = {"web_search_requests": searches}
    return {"id": "msg_or_1", "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": stop_reason, "stop_sequence": None,
            "usage": usage_body}


TEXT = [{"type": "text", "text": "Try a smaller step."}]
SOURCES = [{"type": "text", "text": '[{"title": "T", "url": "https://example.org/a", '
                                    '"tier": 1}]'}]


class Wire:
    """Serves canned bodies and keeps every request the SDK sent."""

    def __init__(self, *bodies):
        self.bodies = list(bodies)
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(200, json=self.bodies[len(self.requests) - 1])

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    def sent(self, i=0) -> dict:
        return json.loads(self.requests[i].content)


@pytest.fixture
def openrouter(monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", OPENROUTER_KEY)
    monkeypatch.setattr(settings, "reasoning_model", "")
    monkeypatch.setattr(settings, "copy_model", "")
    monkeypatch.setattr(settings, "daily_budget_usd", None)


@pytest.fixture
def anthropic_creds_in_env(monkeypatch):
    """Every way the SDK could pick up an Anthropic credential or endpoint on its own."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", ANTHROPIC_TOKEN)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://api.anthropic.com")
    # A custom header the SDK merges in, in both spellings.
    monkeypatch.setenv("ANTHROPIC_CUSTOM_HEADERS",
                       f"x-api-key: {ANTHROPIC_KEY}\nX-Api-Key: {ANTHROPIC_KEY}\n"
                       f"authorization: Bearer {ANTHROPIC_TOKEN}")


def _assert_openrouter_only(request: httpx.Request):
    assert str(request.url) == "https://openrouter.ai/api/v1/messages"
    assert request.headers.get_list("authorization") == [f"Bearer {OPENROUTER_KEY}"]
    assert "x-api-key" not in request.headers
    raw = "\n".join(f"{k}: {v}" for k, v in request.headers.multi_items())
    raw += "\n" + request.content.decode()
    assert ANTHROPIC_KEY not in raw
    assert ANTHROPIC_TOKEN not in raw
    assert "sk-ant" not in raw


# --- the Anthropic key never reaches OpenRouter ------------------------------------------


def test_anthropic_key_is_never_sent_to_openrouter(session, openrouter, anthropic_creds_in_env):
    wire = Wire(_message(TEXT), _message([{"type": "tool_use", "id": "toolu_1",
                                           "name": "emit", "input": {"score": 1}}],
                                         stop_reason="tool_use"),
                _message(SOURCES))
    llm = AnthropicLLMClient(role="reasoning", http_client=wire.http_client())
    llm.complete("SYS", [USER], [])
    llm.complete_json("SYS", [USER], schema=SCHEMA, tool_name="emit")
    AnthropicResearcherClient(http_client=wire.http_client()).search(
        SearchBrief(angle="a", query="q"))

    assert len(wire.requests) == 3
    for request in wire.requests:
        _assert_openrouter_only(request)


def test_openrouter_key_is_never_sent_to_anthropic(session, monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", OPENROUTER_KEY)
    monkeypatch.setattr(settings, "reasoning_model", "")
    wire = Wire(_message(TEXT, model="claude-sonnet-5-5", cost=None))
    AnthropicLLMClient(http_client=wire.http_client()).complete("SYS", [USER], [])
    [request] = wire.requests
    assert str(request.url) == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant-test-not-a-real-key"
    assert "authorization" not in request.headers
    assert OPENROUTER_KEY not in request.content.decode()
    assert "provider" not in wire.sent()


def test_missing_openrouter_key_names_it(openrouter, monkeypatch):
    from adaptive_academy.llm.keys import MissingAPIKeyError

    monkeypatch.delenv("OPENROUTER_API_KEY")
    monkeypatch.setenv("ANTHROPIC_API_KEY", ANTHROPIC_KEY)  # not a substitute
    for ctor in (AnthropicLLMClient, AnthropicResearcherClient):
        with pytest.raises(MissingAPIKeyError, match="OPENROUTER_API_KEY"):
            ctor()


# --- the request ---------------------------------------------------------------------------


def test_requests_carry_the_slug_and_the_privacy_preference(session, openrouter):
    wire = Wire(_message(TEXT), _message(SOURCES))
    AnthropicLLMClient(role="copy", http_client=wire.http_client()).complete("S", [USER], [])
    AnthropicResearcherClient(http_client=wire.http_client()).search(
        SearchBrief(angle="a", query="q"))
    tutor, research = wire.sent(0), wire.sent(1)
    assert tutor["model"] == "anthropic/claude-haiku-5.5"
    assert research["model"] == "anthropic/claude-sonnet-5.5"
    for body in (tutor, research):
        assert body["provider"] == {"data_collection": "deny"}
    # Claude through OpenRouter keeps Anthropic's own web search tool.
    assert research["tools"] == [{"type": "web_search_20250305", "name": "web_search",
                                  "max_uses": 5}]
    # Anthropic's max_uses is the cap for Claude; OpenRouter's loop stop is not sent.
    assert "stop_server_tools_when" not in research


def test_non_claude_research_uses_openrouter_web_search(session, openrouter, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_model", "deepseek/deepseek-v4")
    wire = Wire(_message(SOURCES, model="deepseek/deepseek-v4"))
    sources = AnthropicResearcherClient(http_client=wire.http_client()).search(
        SearchBrief(angle="a", query="q"))
    assert [s.url for s in sources] == ["https://example.org/a"]
    body = wire.sent()
    assert body["tools"] == [{"type": "openrouter:web_search",
                              "parameters": {"max_uses": 5}}]
    # max_uses alone doesn't bind native search (or stop the model asking), so the
    # server-tool loop itself stops at the cap, beside the privacy preference.
    assert body["stop_server_tools_when"] == [{"type": "step_count_is", "step_count": 5}]
    assert body["provider"] == {"data_collection": "deny"}


def test_non_claude_research_cap_follows_max_searches(session, openrouter, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_model", "deepseek/deepseek-v4")
    wire = Wire(_message(SOURCES, model="deepseek/deepseek-v4"))
    AnthropicResearcherClient(max_searches=1, http_client=wire.http_client()).search(
        SearchBrief(angle="a", query="q"))
    body = wire.sent()
    assert body["tools"][0]["parameters"] == {"max_uses": 1}
    assert body["stop_server_tools_when"] == [{"type": "step_count_is", "step_count": 1}]


# --- the search budget across pause_turn continuations ------------------------------------

# Each continuation is a new request, and max_uses (and the loop stop) count per request, so
# a continuation carries only what is left of the angle's cap.
PAUSED = [{"type": "text", "text": "Searching."},
          {"type": "server_tool_use", "id": "srvtoolu_9", "name": "web_search",
           "input": {"query": "q"}}]
PAUSED_WITH_SOURCES = [*SOURCES, PAUSED[1]]
DEEPSEEK = "deepseek/deepseek-v4"


def _search_caps(body) -> tuple:
    """(the tool's max_uses, the loop stop's step_count or None) from a request body."""
    [tool] = body["tools"]
    max_uses = tool.get("max_uses", tool.get("parameters", {}).get("max_uses"))
    stop = body.get("stop_server_tools_when")
    return max_uses, (stop[0]["step_count"] if stop else None)


@pytest.mark.parametrize(("model", "loop_stop"), [
    ("anthropic/claude-sonnet-5.5", False), (DEEPSEEK, True)])
def test_a_continuation_carries_only_the_remaining_search_budget(
        session, openrouter, monkeypatch, model, loop_stop):
    monkeypatch.setattr(settings, "reasoning_model", model)
    wire = Wire(_message(PAUSED, model=model, stop_reason="pause_turn", searches=3),
                _message(SOURCES, model=model, searches=2))
    sources = AnthropicResearcherClient(http_client=wire.http_client()).search(
        SearchBrief(angle="a", query="q"))
    assert [s.url for s in sources] == ["https://example.org/a"]
    assert len(wire.requests) == 2
    assert _search_caps(wire.sent(0)) == (5, 5 if loop_stop else None)
    assert _search_caps(wire.sent(1)) == (2, 2 if loop_stop else None)
    # Still the same tool (a paused turn may end on a search that hasn't run yet).
    assert wire.sent(1)["tools"][0]["type"] == wire.sent(0)["tools"][0]["type"]


@pytest.mark.parametrize("model", ["anthropic/claude-sonnet-5.5", DEEPSEEK])
def test_a_spent_search_budget_ends_the_turn_with_the_text_so_far(session, openrouter,
                                                                  monkeypatch, model):
    monkeypatch.setattr(settings, "reasoning_model", model)
    wire = Wire(_message(PAUSED_WITH_SOURCES, model=model, stop_reason="pause_turn",
                         searches=5))
    sources = AnthropicResearcherClient(http_client=wire.http_client()).search(
        SearchBrief(angle="a", query="q"))
    # No continuation: it could only search again (the pending search would run first).
    assert len(wire.requests) == 1
    assert [s.url for s in sources] == ["https://example.org/a"]
    [row] = session.exec(select(LLMUsage)).all()
    assert row.web_search_requests == 5


def test_the_budget_adds_up_over_several_continuations(session, openrouter, monkeypatch):
    monkeypatch.setattr(settings, "reasoning_model", DEEPSEEK)
    wire = Wire(_message(PAUSED, model=DEEPSEEK, stop_reason="pause_turn", searches=1),
                _message(PAUSED, model=DEEPSEEK, stop_reason="pause_turn", searches=2),
                _message(PAUSED, model=DEEPSEEK, stop_reason="pause_turn", searches=2))
    AnthropicResearcherClient(http_client=wire.http_client()).search(
        SearchBrief(angle="a", query="q"))
    assert [_search_caps(wire.sent(i)) for i in range(len(wire.requests))] == [
        (5, 5), (4, 4), (2, 2)]


def test_non_claude_structured_output_drops_strict_but_keeps_the_retry(session, openrouter,
                                                                      monkeypatch):
    monkeypatch.setattr(settings, "reasoning_model", "deepseek/deepseek-v4")
    wire = Wire(_message(TEXT, model="deepseek/deepseek-v4"),
                _message([{"type": "tool_use", "id": "toolu_1", "name": "emit",
                           "input": {"score": 0.5}}], model="deepseek/deepseek-v4",
                         stop_reason="tool_use"))
    out = AnthropicLLMClient(http_client=wire.http_client()).complete_json(
        "SYS", [USER], schema=SCHEMA, tool_name="emit")
    assert out == {"score": 0.5}
    assert len(wire.requests) == 2
    [tool] = wire.sent(0)["tools"]
    assert "strict" not in tool
    assert tool["input_schema"]["additionalProperties"] is False


def test_claude_structured_output_stays_strict(session, openrouter):
    wire = Wire(_message([{"type": "tool_use", "id": "toolu_1", "name": "emit",
                           "input": {"score": 0.5}}], stop_reason="tool_use"))
    AnthropicLLMClient(http_client=wire.http_client()).complete_json(
        "SYS", [USER], schema=SCHEMA, tool_name="emit")
    assert wire.sent()["tools"][0]["strict"] is True


def test_thinking_blocks_are_replayed_only_for_models_that_support_it(session, openrouter,
                                                                      monkeypatch):
    blocks = [{"type": "thinking", "thinking": "", "signature": "sig"},
              {"type": "text", "text": "Hi"}]
    claude = AnthropicLLMClient(http_client=Wire(_message(blocks)).http_client())
    assert [b["type"] for b in claude.complete("S", [USER], []).raw_content] == [
        "thinking", "text"]
    monkeypatch.setattr(settings, "reasoning_model", "deepseek/deepseek-v4")
    other = AnthropicLLMClient(http_client=Wire(
        _message(blocks, model="deepseek/deepseek-v4")).http_client())
    resp = other.complete("S", [USER], [])
    assert [b["type"] for b in resp.raw_content] == ["text"]
    assert resp.text == "Hi"


# --- cost and the daily limit --------------------------------------------------------------


def _rows(session) -> list[LLMUsage]:
    return list(session.exec(select(LLMUsage).order_by(LLMUsage.id)).all())


def test_usage_row_records_backend_and_reported_cost(session, openrouter):
    AnthropicLLMClient(http_client=Wire(_message(TEXT, cost=0.0123)).http_client()).complete(
        "S", [USER], [])
    [row] = _rows(session)
    assert row.backend == "openrouter"
    assert row.model == "anthropic/claude-sonnet-5.5"
    assert row.reported_cost_usd == pytest.approx(0.0123)
    assert (row.input_tokens, row.output_tokens) == (100, 20)


def test_unpriced_model_runs_under_a_limit_when_openrouter_reports_cost(session, openrouter,
                                                                       monkeypatch):
    monkeypatch.setattr(settings, "daily_budget_usd", 5.0)
    monkeypatch.setattr(settings, "reasoning_model", "deepseek/deepseek-v4")
    wire = Wire(_message(TEXT, model="deepseek/deepseek-v4", cost=0.002))
    assert AnthropicLLMClient(http_client=wire.http_client()).complete("S", [USER], []).text
    assert usage.spent_today_usd() == pytest.approx(0.002)
    assert usage.budget_warnings() == []


def test_reported_cost_counts_toward_the_limit(session, openrouter, monkeypatch):
    monkeypatch.setattr(settings, "daily_budget_usd", 0.01)
    llm = AnthropicLLMClient(http_client=Wire(_message(TEXT, cost=0.02)).http_client())
    llm.complete("S", [USER], [])
    with pytest.raises(usage.BudgetExceededError):
        llm.complete("S", [USER], [])
