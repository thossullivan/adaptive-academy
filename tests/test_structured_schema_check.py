"""A structured answer from a model without strict tool use is checked against the schema it
was sent. The live failure: OpenRouter + deepseek/deepseek-v4.1-flash-1017 returned a
curriculum phase as a string, and POST /api/topics/{id}/curriculum crashed with a bare 500
(AttributeError in parse_curriculum_obj). Now the violation gets one corrective retry that
names it, and a second bad answer is a legible 502 (category invalid_output).

The tool path here runs on Claude before 4.5 (structured_output "tool"). Non-Claude models
use output_config.format instead of a tool (tests/test_structured_json_schema.py).

Offline: requests go through the real Anthropic SDK to an httpx MockTransport."""

import copy
import json

import httpx
import pytest
from fastapi.testclient import TestClient

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.engine.curriculum import CURRICULUM_SCHEMA
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.errors import describe_llm_error
from adaptive_academy.llm.structured import structured_json
from adaptive_academy.llm.types import LLMResponse, StructuredOutputError
from adaptive_academy.models import SourceDoc, Topic, TopicFoundation, TopicIntent
from adaptive_academy.prompts import STRUCTURED_SCHEMA_RETRY
from adaptive_academy.settings import settings

LEGACY = "claude-sonnet-4-0"  # Claude before 4.5: a tool without `strict`
USER ={"role": "user", "content": "Build the track."}
GOOD = {
    "overview": "A path",
    "phases": [{"title": "P1", "est_hours": "1w",
                "items": [{"type": "read", "text": "paper", "concept_refs": ["la"]}],
                "deliverable": {"kind": "blog", "text": "post"}}],
}
# The live shape: one phase came back as a string.
LIVE_BAD = {**GOOD, "phases": [*GOOD["phases"], "Phase 2: Attention"]}


def _tool_message(model, answer, *, tool_id="toolu_1", thinking=False):
    content = [{"type": "tool_use", "id": tool_id, "name": "emit_track", "input": answer}]
    if thinking:
        content.insert(0, {"type": "thinking", "thinking": "plan", "signature": "sig"})
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": model,
            "content": content, "stop_reason": "tool_use", "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 10,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                      "cost": 0.0001}}


class Wire:
    def __init__(self, *bodies):
        self.bodies = list(bodies)
        self.requests: list[dict] = []

    def _handle(self, request):
        self.requests.append(json.loads(request.content))
        return httpx.Response(200, json=self.bodies[len(self.requests) - 1])

    def http_client(self):
        return httpx.Client(transport=httpx.MockTransport(self._handle))


@pytest.fixture
def legacy(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test-not-a-real-key")
    monkeypatch.setattr(settings, "reasoning_model", LEGACY)
    monkeypatch.setattr(settings, "copy_model", LEGACY)


def _complete(wire):
    return AnthropicLLMClient(http_client=wire.http_client()).complete_json(
        "S", [USER], schema=CURRICULUM_SCHEMA, tool_name="emit_track")


def test_live_shape_gets_one_named_correction_then_succeeds(session, legacy):
    wire = Wire(_tool_message(LEGACY, LIVE_BAD),
                _tool_message(LEGACY, GOOD, tool_id="toolu_2"))
    assert _complete(wire) == GOOD
    assert len(wire.requests) == 2
    first, retry = wire.requests
    assert "strict" not in first["tools"][0]
    # Append-only: the original turn, the model's own turn, then the correction.
    assert retry["messages"][0] == USER
    assistant, correction = retry["messages"][1:]
    assert assistant["role"] == "assistant"
    assert [b["type"] for b in assistant["content"]] == ["tool_use"]
    assert assistant["content"][0]["input"] == LIVE_BAD
    [result] = correction["content"]
    assert correction["role"] == "user"
    assert result["type"] == "tool_result" and result["tool_use_id"] == "toolu_1"
    assert result["is_error"] is True
    assert "$.phases[1]: expected object, got string 'Phase 2: Attention'" in result["content"]
    assert "emit_track" in result["content"]
    # Tools and system are unchanged, so the cached prefix still matches.
    assert retry["tools"] == first["tools"] and retry["system"] == first["system"]


def test_two_bad_answers_are_invalid_output(session, legacy):
    wire = Wire(_tool_message(LEGACY, LIVE_BAD), _tool_message(LEGACY, LIVE_BAD))
    with pytest.raises(StructuredOutputError) as caught:
        _complete(wire)
    assert len(wire.requests) == 2
    assert caught.value.reason == "schema_mismatch"
    assert "$.phases[1]" in str(caught.value)
    failure = describe_llm_error(caught.value)
    assert (failure.category, failure.status_code) == ("invalid_output", 502)
    assert "retry" in failure.detail.lower()


def test_bad_answer_then_prose_is_no_tool_use(session, legacy):
    prose = _tool_message(LEGACY, GOOD)
    prose["content"] = [{"type": "text", "text": "Here is the track: ..."}]
    prose["stop_reason"] = "end_turn"
    wire = Wire(_tool_message(LEGACY, LIVE_BAD), prose)
    with pytest.raises(StructuredOutputError) as caught:
        _complete(wire)
    assert caught.value.reason == "no_tool_use"


def test_prose_then_bad_answer_is_schema_mismatch(session, legacy):
    prose = _tool_message(LEGACY, GOOD)
    prose["content"] = [{"type": "text", "text": "Sure."}]
    prose["stop_reason"] = "end_turn"
    wire = Wire(prose, _tool_message(LEGACY, LIVE_BAD))
    with pytest.raises(StructuredOutputError) as caught:
        _complete(wire)
    assert caught.value.reason == "schema_mismatch"


def test_a_valid_first_answer_costs_one_call(session, legacy):
    wire = Wire(_tool_message(LEGACY, GOOD))
    assert _complete(wire) == GOOD
    assert len(wire.requests) == 1


def test_legacy_claude_is_checked_and_keeps_its_thinking(session, monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test-not-a-real-key")
    monkeypatch.setattr(settings, "reasoning_model", "claude-sonnet-4-0")
    wire = Wire(_tool_message("claude-sonnet-4-0", LIVE_BAD, thinking=True),
                _tool_message("claude-sonnet-4-0", GOOD, tool_id="toolu_2"))
    assert _complete(wire) == GOOD
    assistant = wire.requests[1]["messages"][1]
    # Claude replays thinking blocks unchanged within the exchange.
    assert [b["type"] for b in assistant["content"]] == ["thinking", "tool_use"]
    assert assistant["content"][0]["signature"] == "sig"


def test_strict_claude_is_not_rechecked(session, monkeypatch):
    """`strict: true` guarantees the shape; the answer is passed through as before (one call,
    no correction), so the strict path's requests and behaviour are unchanged."""
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-api03-test-not-a-real-key")
    monkeypatch.setattr(settings, "reasoning_model", "claude-sonnet-5-5")
    wire = Wire(_tool_message("claude-sonnet-5-5", LIVE_BAD))
    assert _complete(wire) == LIVE_BAD
    assert len(wire.requests) == 1
    assert wire.requests[0]["tools"][0]["strict"] is True


def test_correction_prompt_is_versioned():
    assert STRUCTURED_SCHEMA_RETRY.tag == "structured.schema_retry@v1"
    text = STRUCTURED_SCHEMA_RETRY.format(violations="- $.a: bad", resend="RESEND")
    assert "- $.a: bad" in text and "RESEND" in text


# --- the route: a legible 502, not a bare 500 ------------------------------------------


def _topic(session) -> Topic:
    topic = Topic(title="Transformers")
    session.add(topic)
    session.commit()
    session.add(TopicIntent(topic_id=topic.id, goal="g"))
    session.add(TopicFoundation(topic_id=topic.id, overview="o", key_concepts=["la"],
                                prerequisite_map={}))
    session.add(SourceDoc(topic_id=topic.id, title="S", url="u", tier=1, status="accepted"))
    session.commit()
    return topic


def _route_client(session, wire) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_llm] = lambda: AnthropicLLMClient(
        http_client=wire.http_client())
    return TestClient(app)


def test_curriculum_route_two_bad_answers_is_a_legible_502(session, legacy):
    topic = _topic(session)
    wire = Wire(_tool_message(LEGACY, LIVE_BAD), _tool_message(LEGACY, LIVE_BAD))
    r = _route_client(session, wire).post(f"/api/topics/{topic.id}/curriculum")
    assert r.status_code == 502, r.text
    assert r.json()["category"] == "invalid_output"
    assert "retry" in r.json()["detail"].lower()


def test_curriculum_route_recovers_after_the_correction(session, legacy):
    topic = _topic(session)
    wire = Wire(_tool_message(LEGACY, LIVE_BAD), _tool_message(LEGACY, GOOD))
    r = _route_client(session, wire).post(f"/api/topics/{topic.id}/curriculum")
    assert r.status_code == 200, r.text
    assert len(wire.requests) == 2


# --- the text path (Agent SDK client, fakes): the same check ---------------------------


class TextQueue:
    """A client without complete_json: answers in text, records what it was sent."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls: list[list[dict]] = []

    def complete(self, system, messages, tools):
        self.calls.append(copy.deepcopy(messages))
        answer = self.answers.pop(0)
        return LLMResponse(text=answer if isinstance(answer, str) else json.dumps(answer))


def _text_structured(llm):
    return structured_json(llm, "S", [USER], schema=CURRICULUM_SCHEMA, tool_name="emit_track")


def test_text_path_live_shape_gets_one_correction(session):
    llm = TextQueue(LIVE_BAD, "```json\n" + json.dumps(GOOD) + "\n```")
    assert _text_structured(llm) == GOOD
    assert len(llm.calls) == 2
    _, assistant, correction = llm.calls[1]
    assert assistant == {"role": "assistant", "content": json.dumps(LIVE_BAD)}
    assert correction["role"] == "user"
    assert "$.phases[1]: expected object" in correction["content"]


def test_text_path_two_bad_answers_is_invalid_output(session):
    llm = TextQueue(LIVE_BAD, {"overview": "o", "phases": "none"})
    with pytest.raises(StructuredOutputError) as caught:
        _text_structured(llm)
    assert caught.value.reason == "schema_mismatch"
    assert describe_llm_error(caught.value).category == "invalid_output"


def test_text_path_valid_answer_costs_one_call(session):
    llm = TextQueue(GOOD)
    assert _text_structured(llm) == GOOD
    assert len(llm.calls) == 1
