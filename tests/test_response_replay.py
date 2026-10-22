"""Replay full Messages API responses through the real Anthropic SDK and our clients.

The rest of the suite fakes `messages.create` (or uses the scripted client), so the SDK's own
response parsing and our block handling never meet a real response shape. Here each response
body in tests/fixtures/anthropic_responses/ is served over HTTP by an httpx MockTransport
handed to the real `Anthropic` client (the `http_client=` seam on AnthropicLLMClient and
AnthropicResearcherClient). The SDK builds the real request, parses the real response into
its own types, and our code reads those, end to end. No socket is opened.

Fixture files: a Messages API response body (or error body) plus underscore keys that are
stripped before replay: `_source` ("documented": built from the shapes in the claude-api
skill; "recorded": captured by scripts/record_response_fixtures.py), `_note` (what it
represents), and for errors `_status` and `_headers`.
"""

import json
from pathlib import Path

import anthropic
import httpx
import pytest
from sqlmodel import select

from adaptive_academy.engine.tools import TOOLS
from adaptive_academy.llm import registry
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient
from adaptive_academy.llm.errors import classify_llm_error, describe_llm_error
from adaptive_academy.llm.researcher_types import SearchBrief
from adaptive_academy.llm.types import StructuredOutputError
from adaptive_academy.models import LLMUsage
from adaptive_academy.prompts import STRUCTURED_TOOL_RETRY

FIXTURES = Path(__file__).parent / "fixtures" / "anthropic_responses"
MODEL = "claude-sonnet-5-5"
SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "verdict": {"type": "string"},
        "gaps": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "verdict", "gaps"],
}


def _fixture(name: str) -> dict:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _body(name: str) -> dict:
    """The response body exactly as the API would send it (metadata keys stripped)."""
    return {k: v for k, v in _fixture(name).items() if not k.startswith("_")}


def _canonical(value) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


class Replay:
    """Serves fixtures in order to the SDK's HTTP client and records every request.

    `repeat_last` keeps serving the last fixture, for the SDK's own retries on 429/529.
    Retryable errors get `retry-after-ms: 1` so the SDK's backoff takes a millisecond
    instead of seconds; the retry count itself is the real SDK behaviour.
    """

    def __init__(self, *names: str, repeat_last: bool = False):
        self.names = list(names)
        self.repeat_last = repeat_last
        self.requests: list[httpx.Request] = []

    def _handle(self, request: httpx.Request) -> httpx.Response:
        assert request.method == "POST" and request.url.path == "/v1/messages"
        self.requests.append(request)
        index = len(self.requests) - 1
        if index >= len(self.names):
            assert self.repeat_last, f"unexpected extra request #{index + 1}"
            index = len(self.names) - 1
        fixture = _fixture(self.names[index])
        status = fixture.get("_status", 200)
        headers = {"request-id": f"req_replay_{index + 1:04d}", **fixture.get("_headers", {})}
        if status == 429 or status >= 500:
            headers["retry-after-ms"] = "1"
        return httpx.Response(status, json=_body(self.names[index]), headers=headers)

    def http_client(self) -> httpx.Client:
        return httpx.Client(transport=httpx.MockTransport(self._handle))

    @property
    def bodies(self) -> list[dict]:
        return [json.loads(r.content) for r in self.requests]


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    # Pin the model whatever the developer's .env says, so costs are known.
    monkeypatch.setattr(registry._settings.settings, "reasoning_model", "")


def _llm(replay: Replay) -> AnthropicLLMClient:
    return AnthropicLLMClient(role="reasoning", http_client=replay.http_client())


def _researcher(replay: Replay) -> AnthropicResearcherClient:
    return AnthropicResearcherClient(role="reasoning", http_client=replay.http_client())


def _usage_rows(session) -> list[LLMUsage]:
    return list(session.exec(select(LLMUsage).order_by(LLMUsage.id)).all())


USER = {"role": "user", "content": "I think a big learning rate makes it overshoot?"}


# --- fixture hygiene ---------------------------------------------------------------------


def test_every_fixture_is_labelled_and_parses_as_a_response_body():
    files = sorted(FIXTURES.glob("*.json"))
    assert len(files) >= 15
    for path in files:
        doc = json.loads(path.read_text())
        assert doc.get("_source") in ("documented", "recorded"), path.name
        assert isinstance(doc.get("_note"), str) and doc["_note"], path.name
        body = {k: v for k, v in doc.items() if not k.startswith("_")}
        assert body["type"] in ("message", "error"), path.name
        if body["type"] == "error":
            assert doc["_status"] >= 400 and body["error"]["type"], path.name


# --- tutor: AnthropicLLMClient.complete ----------------------------------------------------


def test_tutor_reply_separates_thinking_from_text_and_keeps_raw_blocks(session, api_key):
    replay = Replay("tutor_reply_thinking_text")
    resp = _llm(replay).complete("SYS", [USER], TOOLS)

    fixture = _body("tutor_reply_thinking_text")
    assert resp.text == fixture["content"][1]["text"]  # the thinking block is not reply text
    assert resp.tool_calls == []
    assert resp.stop_reason == "end_turn"
    # Every block, thinking included, comes back exactly as the API sent it.
    assert _canonical(resp.raw_content) == _canonical(fixture["content"])
    assert resp.raw_content[0] == {"type": "thinking", "thinking": "",
                                   "signature": fixture["content"][0]["signature"]}

    [request] = replay.requests
    assert request.url == "https://api.anthropic.com/v1/messages"
    assert request.headers["x-api-key"] == "sk-ant-test-not-a-real-key"
    sent = replay.bodies[0]
    assert sent["model"] == MODEL and sent["cache_control"] == {"type": "ephemeral"}

    [row] = _usage_rows(session)
    assert (row.operation, row.model, row.backend) == ("complete", MODEL, "anthropic")
    assert (row.input_tokens, row.output_tokens) == (412, 236)
    assert (row.cache_creation_input_tokens, row.cache_read_input_tokens) == (2000, 0)
    assert row.web_search_requests == 0
    # 412 in x $2 + 236 out x $10 + 1500 5m-writes x $2.50 + 500 1h-writes x $4, per MTok.
    assert row.cost_usd == pytest.approx(0.008934)


def test_tutor_tool_turn_then_echo_sends_the_blocks_back_byte_for_byte(session, api_key):
    replay = Replay("tutor_tool_use_turn", "tutor_tool_followup_text")
    llm = _llm(replay)
    turn = llm.complete("SYS", [USER], TOOLS)

    blocks = _body("tutor_tool_use_turn")["content"]
    assert turn.stop_reason == "tool_use"
    assert turn.text == ""  # the progress-update thinking block is not reply text
    assert [(c.id, c.name, c.input) for c in turn.tool_calls] == [
        (blocks[1]["id"], "log_attempt", blocks[1]["input"]),
        (blocks[3]["id"], "reveal_solution", blocks[3]["input"]),
    ]
    assert _canonical(turn.raw_content) == _canonical(blocks)

    # The tutor's echo (engine/tutor.py): the assistant turn's raw blocks, then the results.
    results = [{"type": "tool_result", "tool_use_id": c.id, "content": "ok"}
               for c in turn.tool_calls]
    messages = [USER, {"role": "assistant", "content": turn.raw_content},
                {"role": "user", "content": results}]
    reply = llm.complete("SYS", messages, TOOLS)

    sent = replay.bodies[1]["messages"]
    assert sent[0] == USER
    assert sent[1]["role"] == "assistant"
    assert _canonical(sent[1]["content"]) == _canonical(blocks)
    assert sent[2]["content"] == results
    # The signatures cross the wire as the exact strings received, empty thinking included.
    raw = replay.requests[1].content.decode()
    for block in blocks:
        if block["type"] == "thinking":
            assert json.dumps(block["signature"]) in raw
    assert '"thinking":""' in raw.replace(" ", "")

    assert reply.text == _body("tutor_tool_followup_text")["content"][1]["text"]
    assert reply.stop_reason == "end_turn"

    rows = _usage_rows(session)
    assert [r.operation for r in rows] == ["complete", "complete"]
    assert [(r.cache_creation_input_tokens, r.cache_read_input_tokens) for r in rows] == [
        (1210, 2412), (310, 3622)]
    assert rows[0].cost_usd == pytest.approx(0.0053382)
    assert rows[1].cost_usd == pytest.approx(0.0024212)


def test_tutor_refusal_surfaces_as_stop_reason_with_no_text(session, api_key):
    resp = _llm(Replay("json_refusal")).complete("SYS", [USER], TOOLS)
    assert (resp.stop_reason, resp.text, resp.tool_calls, resp.raw_content) == (
        "refusal", "", [], [])
    assert len(_usage_rows(session)) == 1  # a decline is still a recorded call


# --- structured output: AnthropicLLMClient.complete_json ----------------------------------


def test_complete_json_returns_the_strict_tool_input(session, api_key):
    replay = Replay("json_strict_tool_use")
    out = _llm(replay).complete_json("SYS", [USER], schema=SCHEMA, tool_name="emit_grade")

    assert out == _body("json_strict_tool_use")["content"][1]["input"]
    [sent] = replay.bodies
    assert sent["tool_choice"] == {"type": "auto", "disable_parallel_tool_use": True}
    [tool] = sent["tools"]
    assert tool["name"] == "emit_grade" and tool["strict"] is True
    assert tool["input_schema"]["additionalProperties"] is False
    [row] = _usage_rows(session)
    assert row.operation == "complete_json"
    assert row.cost_usd == pytest.approx(0.005208)


def test_complete_json_text_only_answer_gets_one_corrective_retry(session, api_key):
    replay = Replay("json_text_only", "json_strict_tool_use")
    out = _llm(replay).complete_json("SYS", [USER], schema=SCHEMA, tool_name="emit_grade")

    assert out["verdict"] == "partial"
    first, second = replay.bodies
    assert first["messages"] == [USER]
    # Append-only correction: the original turn unchanged, then a new user turn.
    assert second["messages"] == [
        USER, {"role": "user", "content": STRUCTURED_TOOL_RETRY.format(tool_name="emit_grade")}]
    assert {k: v for k, v in first.items() if k != "messages"} == {
        k: v for k, v in second.items() if k != "messages"}
    rows = _usage_rows(session)
    assert len(rows) == 2
    assert rows[0].cost_usd == pytest.approx(0.003678)


def test_complete_json_two_prose_answers_fail_as_no_tool_use(session, api_key):
    replay = Replay("json_text_only", "json_text_only")
    with pytest.raises(StructuredOutputError) as caught:
        _llm(replay).complete_json("SYS", [USER], schema=SCHEMA, tool_name="emit_grade")
    assert caught.value.reason == "no_tool_use"
    assert classify_llm_error(caught.value) == "invalid_output"
    assert len(replay.requests) == 2 and len(_usage_rows(session)) == 2


@pytest.mark.parametrize(("fixture", "reason", "category"), [
    ("json_refusal", "refusal", "refusal"),
    ("json_max_tokens", "max_tokens", "cut_off"),
    ("json_context_window_exceeded", "model_context_window_exceeded", "cut_off"),
])
def test_complete_json_stop_reasons_fail_fast_without_a_retry(
        session, api_key, fixture, reason, category):
    replay = Replay(fixture)
    with pytest.raises(StructuredOutputError) as caught:
        _llm(replay).complete_json("SYS", [USER], schema=SCHEMA, tool_name="emit_grade")
    assert caught.value.reason == reason
    assert classify_llm_error(caught.value) == category
    assert describe_llm_error(caught.value).status_code == 502
    assert len(replay.requests) == 1  # no corrective retry: it would fail the same way
    [row] = _usage_rows(session)  # billed, so recorded
    assert row.output_tokens == _body(fixture)["usage"]["output_tokens"]


def test_refusal_stop_details_parse_into_the_sdk_type(api_key):
    # Our code branches on stop_reason only; this pins that the SDK still reads the details.
    client = anthropic.Anthropic(api_key="sk-ant-test-not-a-real-key",
                                 http_client=Replay("json_refusal").http_client())
    message = client.messages.create(model=MODEL, max_tokens=10,
                                     messages=[{"role": "user", "content": "x"}])
    assert message.stop_reason == "refusal" and message.content == []
    assert message.stop_details.category == "cyber"
    assert message.stop_details.explanation


# --- research: AnthropicResearcherClient.search --------------------------------------------


def test_research_pause_turn_is_continued_with_the_paused_content_unchanged(session, api_key):
    replay = Replay("research_pause_turn", "research_continuation_end_turn")
    sources = _researcher(replay).search(
        SearchBrief(angle="foundations", query="gradient descent step size"))

    assert [(s.url, s.tier, s.angle) for s in sources] == [
        ("https://www.cs.cornell.edu/courses/cs4780/2023fa/lectures/gd.html", 1,
         "foundations"),
        ("https://arxiv.org/abs/1609.04747", 2, "foundations"),
    ]
    assert sources[0].relevance == pytest.approx(0.92)

    first, second = replay.bodies
    user = {"role": "user", "content": "gradient descent step size"}
    assert first["messages"] == [user]
    assert first["tools"] == [{"type": "web_search_20250305", "name": "web_search",
                               "max_uses": 5}]
    # The continuation re-sends the paused turn exactly (server_tool_use, the encrypted
    # search results, the trailing not-yet-run search) and adds no "continue" message.
    assert len(second["messages"]) == 2
    assert second["messages"][0] == user
    assert second["messages"][1]["role"] == "assistant"
    assert _canonical(second["messages"][1]["content"]) == _canonical(
        _body("research_pause_turn")["content"])
    assert {k: v for k, v in first.items() if k != "messages"} == {
        k: v for k, v in second.items() if k != "messages"}

    rows = _usage_rows(session)
    assert [r.operation for r in rows] == ["research_search", "research_search"]
    assert [r.web_search_requests for r in rows] == [1, 1]
    assert [(r.cache_creation_input_tokens, r.cache_read_input_tokens) for r in rows] == [
        (0, 1980), (2904, 1980)]
    # Tokens at Sonnet 5.5 rates plus $10 per 1,000 searches.
    assert rows[0].cost_usd == pytest.approx(0.008738 + 0.01)
    assert rows[1].cost_usd == pytest.approx(0.014644 + 0.01)


# --- errors: the SDK's typed exceptions → llm/errors.py categories -------------------------


@pytest.mark.parametrize(("fixture", "exc_type", "category", "attempts"), [
    ("error_400_credit_balance", anthropic.BadRequestError, "out_of_credits", 1),
    ("error_401_authentication", anthropic.AuthenticationError, "auth", 1),
    ("error_404_model_not_found", anthropic.NotFoundError, "model_unavailable", 1),
    # Retryable: the SDK tries 1 + max_retries (3 on the LLM client) times, then raises.
    ("error_429_rate_limit", anthropic.RateLimitError, "rate_limited", 4),
    ("error_529_overloaded", anthropic.OverloadedError, "overloaded", 4),
])
def test_api_errors_map_to_their_category(session, api_key, fixture, exc_type, category,
                                          attempts):
    replay = Replay(fixture, repeat_last=True)
    with pytest.raises(exc_type) as caught:
        _llm(replay).complete("SYS", [USER], [])
    exc = caught.value
    assert exc.status_code == _fixture(fixture)["_status"]
    assert exc.body == _body(fixture)
    assert classify_llm_error(exc) == category
    failure = describe_llm_error(exc)
    assert (failure.category, failure.status_code) == (category, 502)
    assert len(replay.requests) == attempts
    assert _usage_rows(session) == []  # nothing came back, nothing was billed or recorded


def test_credit_balance_detail_quotes_the_api_message(api_key):
    with pytest.raises(anthropic.BadRequestError) as caught:
        _llm(Replay("error_400_credit_balance")).complete("SYS", [USER], [])
    detail = describe_llm_error(caught.value).detail
    assert "out of credits" in detail
    assert "Your credit balance is too low" in detail


def test_model_not_found_detail_names_the_model_and_the_setting(api_key):
    with pytest.raises(anthropic.NotFoundError) as caught:
        _llm(Replay("error_404_model_not_found")).complete("SYS", [USER], [])
    detail = describe_llm_error(caught.value).detail
    assert "'claude-sonnet-3-9'" in detail and "AA_MODEL_REASONING" in detail


def test_researcher_overloaded_retries_twice_then_maps_to_overloaded(api_key):
    replay = Replay("error_529_overloaded", repeat_last=True)
    with pytest.raises(anthropic.OverloadedError) as caught:
        _researcher(replay).search(SearchBrief(angle="a", query="q"))
    assert classify_llm_error(caught.value) == "overloaded"
    assert len(replay.requests) == 3  # 1 + max_retries=2 on the researcher
