"""Each API-key call's usage row says how the call ended (LLMUsage.outcome).

The Usage page's quality scorecard counts refusals, empty replies, cut-off answers and
structured answers in the wrong format per feature and per model from this column. Before it,
a structured-output failure outside grading and the tutor guard was recorded nowhere: the
client raised StructuredOutputError, the API answered 502, and no row said so.

No network: the Anthropic SDK class is replaced by a fake that returns canned responses in
order.
"""

from types import SimpleNamespace

import pytest
from sqlmodel import select

from adaptive_academy.llm import model_catalog, usage
from adaptive_academy.llm.types import StructuredOutputError
from adaptive_academy.models import LLMUsage

MODEL = "claude-sonnet-4-6"
_SCHEMA = {"type": "object", "properties": {"ok": {"type": "boolean"}}, "required": ["ok"]}


def _usage():
    return SimpleNamespace(input_tokens=10, output_tokens=5, cache_creation_input_tokens=0,
                           cache_read_input_tokens=0, server_tool_use=None)


def _resp(*blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=list(blocks), usage=_usage(), stop_reason=stop_reason)


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _tool(input_, name="emit"):
    return SimpleNamespace(type="tool_use", id="t1", name=name, input=input_)


def _fake_anthropic(monkeypatch, responses):
    queue = list(responses)

    class _Messages:
        def create(self, **kw):
            return queue.pop(0)

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr("adaptive_academy.llm.anthropic_client.Anthropic", _FakeAnthropic)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")
    monkeypatch.setattr(usage.settings, "daily_budget_usd", None)

    def make(responses, *, caps=None, model=MODEL):
        from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

        _fake_anthropic(monkeypatch, responses)
        c = AnthropicLLMClient()
        c._model = model
        if caps is not None:
            c._caps = caps
        return c

    return make


def _outcomes(session):
    session.expire_all()
    return [r.outcome for r in session.exec(select(LLMUsage).order_by(LLMUsage.id)).all()]


@pytest.mark.parametrize("response, expected", [
    (_resp(_text("hello")), "ok"),
    (_resp(_tool({"x": 1}, name="log_attempt"), stop_reason="tool_use"), "ok"),
    (_resp(_text("partial"), stop_reason="refusal"), "refusal"),
    (_resp(_text("half an ans"), stop_reason="max_tokens"), "cut_off"),
    (_resp(stop_reason="model_context_window_exceeded"), "cut_off"),
    (_resp(_text("  \n"), stop_reason="end_turn"), "empty"),
    (_resp(stop_reason="end_turn"), "empty"),
])
def test_complete_records_how_the_call_ended(session, client, response, expected):
    client([response]).complete("sys", [{"role": "user", "content": "hi"}], tools=[])
    assert _outcomes(session) == [expected]


def test_complete_json_first_answer_usable(session, client):
    out = client([_resp(_tool({"ok": True}))]).complete_json(
        "sys", [{"role": "user", "content": "x"}], schema=_SCHEMA, tool_name="emit")
    assert out == {"ok": True}
    assert _outcomes(session) == ["ok"]


def test_complete_json_prose_then_tool_records_the_retry(session, client):
    c = client([_resp(_text("here you go")), _resp(_tool({"ok": True}))])
    assert c.complete_json("sys", [{"role": "user", "content": "x"}],
                           schema=_SCHEMA, tool_name="emit") == {"ok": True}
    assert _outcomes(session) == ["invalid_output", "ok"]


def test_complete_json_prose_twice_records_two_invalid_answers(session, client):
    c = client([_resp(_text("no")), _resp(_text("still no"))])
    with pytest.raises(StructuredOutputError) as err:
        c.complete_json("sys", [{"role": "user", "content": "x"}],
                        schema=_SCHEMA, tool_name="emit")
    assert err.value.reason == "no_tool_use"
    assert _outcomes(session) == ["invalid_output", "invalid_output"]


def test_complete_json_schema_mismatch_on_a_non_strict_model(session, client):
    legacy = model_catalog.FAMILIES["anthropic-legacy"]
    c = client([_resp(_tool({"ok": "yes"})), _resp(_tool({"ok": "still"}))],
               caps=legacy, model="claude-sonnet-4-0")
    with pytest.raises(StructuredOutputError) as err:
        c.complete_json("sys", [{"role": "user", "content": "x"}],
                        schema=_SCHEMA, tool_name="emit")
    assert err.value.reason == "schema_mismatch"
    assert _outcomes(session) == ["invalid_output", "invalid_output"]


@pytest.mark.parametrize("stop, expected", [("refusal", "refusal"),
                                            ("max_tokens", "cut_off")])
def test_complete_json_stop_reasons(session, client, stop, expected):
    c = client([_resp(_text("x"), stop_reason=stop)])
    with pytest.raises(StructuredOutputError):
        c.complete_json("sys", [{"role": "user", "content": "x"}],
                        schema=_SCHEMA, tool_name="emit")
    assert _outcomes(session) == [expected]


def test_json_schema_mode_not_json_then_valid(session, client):
    c = client([_resp(_text("I think yes")), _resp(_text('{"ok": true}'))],
               caps=model_catalog.OTHER, model="deepseek/deepseek-v4")
    assert c.complete_json("sys", [{"role": "user", "content": "x"}],
                           schema=_SCHEMA, tool_name="emit") == {"ok": True}
    assert _outcomes(session) == ["invalid_output", "ok"]


def test_json_schema_mode_fails_twice(session, client):
    c = client([_resp(_text('{"ok": 3}')), _resp(_text("nope"))],
               caps=model_catalog.OTHER, model="deepseek/deepseek-v4")
    with pytest.raises(StructuredOutputError):
        c.complete_json("sys", [{"role": "user", "content": "x"}],
                        schema=_SCHEMA, tool_name="emit")
    assert _outcomes(session) == ["invalid_output", "invalid_output"]


def test_an_unexpected_parse_error_still_records_the_billed_call(session, client):
    # A response the client can't even read: the call was billed, so the row is written,
    # with no outcome rather than a guessed one.
    broken = SimpleNamespace(content=None, usage=_usage(), stop_reason="end_turn")
    c = client([broken])
    with pytest.raises(TypeError):
        c.complete_json("sys", [{"role": "user", "content": "x"}],
                        schema=_SCHEMA, tool_name="emit")
    assert _outcomes(session) == [None]


def test_record_usage_without_an_outcome_stores_null(session):
    usage.record_usage(backend="agent_sdk", model=MODEL, role="reasoning",
                       operation="complete", usage=_usage(), total_cost_usd=0.01)
    assert _outcomes(session) == [None]
