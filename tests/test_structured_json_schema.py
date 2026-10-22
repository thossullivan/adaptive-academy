"""Structured output for non-Claude models: no tools, `output_config.format` with the strict
schema (model_catalog structured_output "json_schema").

The live failure: deepseek/deepseek-v4.1-flash-1017 on OpenRouter answered the curriculum's
`emit_track` tool with its own native tool-call markup written as TEXT ("<｜DSML｜ calls>
..."), which OpenRouter didn't turn into a tool_use block, so both attempts were no_tool_use.
The same prompt without tools and with output_config.format returned valid JSON twice.

Offline: requests go through the real Anthropic SDK to an httpx MockTransport."""

import json

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlmodel import select

from adaptive_academy.api.app import create_app
from adaptive_academy.api.deps import get_llm, get_session
from adaptive_academy.engine.curriculum import CURRICULUM_SCHEMA
from adaptive_academy.engine.program_research import PROGRAM_SCHEMA
from adaptive_academy.engine.revision import REVISION_SCHEMA
from adaptive_academy.engine.solution_guard import GUARD_SCHEMA, GUARD_TOOL
from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
from adaptive_academy.llm.errors import describe_llm_error
from adaptive_academy.llm.strict_schema import to_strict_schema
from adaptive_academy.llm.structured import SCOUT_SCHEMA, structured_json
from adaptive_academy.llm.types import StructuredOutputError
from adaptive_academy.models import LLMUsage, SourceDoc, Topic, TopicFoundation, TopicIntent
from adaptive_academy.prompts import STRUCTURED_JSON_INSTRUCTION
from adaptive_academy.settings import settings

DEEPSEEK = "deepseek/deepseek-v4.1-flash-1017"
USER = {"role": "user", "content": "Build the track."}
GOOD = {
    "overview": "A path",
    "phases": [{"title": "P1", "est_hours": "1w",
                "items": [{"type": "read", "text": "paper", "concept_refs": ["la"]}],
                "deliverable": {"kind": "blog", "text": "post"}}],
}
LIVE_BAD = {**GOOD, "phases": [*GOOD["phases"], "Phase 2: Attention"]}
# What the model wrote instead of a tool call (abridged from the live response).
DSML = ('<｜DSML｜ calls> <｜DSML｜ invoke name="emit_track"> <｜DSML｜ parameter '
        'name="overview" string="true">A path</｜DSML｜ parameter> </｜DSML｜ invoke> '
        '</｜DSML｜ calls>')


def _message(*blocks, stop_reason="end_turn"):
    return {"id": "msg_1", "type": "message", "role": "assistant", "model": DEEPSEEK,
            "content": list(blocks), "stop_reason": stop_reason, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 10,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0,
                      "cost": 0.0001}}


def _text(answer):
    return {"type": "text", "text": answer if isinstance(answer, str) else json.dumps(answer)}


THINKING = {"type": "thinking", "thinking": "{\"not\": \"the answer\"}", "signature": "s"}


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
def deepseek(monkeypatch):
    monkeypatch.setenv("AA_LLM_BACKEND", "openrouter")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-v1-test-not-a-real-key")
    monkeypatch.setattr(settings, "reasoning_model", DEEPSEEK)
    monkeypatch.setattr(settings, "copy_model", DEEPSEEK)


def _complete(wire, schema=CURRICULUM_SCHEMA, tool_name="emit_track"):
    return AnthropicLLMClient(http_client=wire.http_client()).complete_json(
        "S", [USER], schema=schema, tool_name=tool_name)


def test_request_has_no_tools_and_asks_for_the_strict_schema(session, deepseek):
    wire = Wire(_message(_text(GOOD)))
    assert _complete(wire) == GOOD
    [request] = wire.requests
    assert "tools" not in request and "tool_choice" not in request
    assert request["output_config"] == {"format": {
        "type": "json_schema", "schema": to_strict_schema(CURRICULUM_SCHEMA)}}
    # The backend's own body fields are kept: OpenRouter's privacy preference.
    assert request["provider"]["data_collection"] == "deny"
    assert request["model"] == DEEPSEEK
    # The tool instruction would point at a tool that isn't there; this says JSON instead.
    system_text = request["system"][0]["text"]
    assert system_text.endswith(STRUCTURED_JSON_INSTRUCTION)
    assert "emit_track" not in system_text


def test_thinking_blocks_are_not_read_as_the_answer(session, deepseek):
    wire = Wire(_message(THINKING, _text(GOOD)))
    assert _complete(wire) == GOOD


def test_fenced_json_is_accepted(session, deepseek):
    wire = Wire(_message(_text("```json\n" + json.dumps(GOOD) + "\n```")))
    assert _complete(wire) == GOOD


def test_usage_is_recorded_as_complete_json(session, deepseek):
    _complete(Wire(_message(_text(LIVE_BAD)), _message(_text(GOOD))))
    rows = session.exec(select(LLMUsage)).all()
    assert [(r.operation, r.model) for r in rows] == [("complete_json", DEEPSEEK)] * 2


@pytest.mark.parametrize("bad", [DSML, "not json at all", '{"overview": "A path", "phases": [',
                                 ""])
def test_unusable_text_gets_one_retry_then_invalid_output(session, deepseek, bad):
    blocks = [_text(bad)] if bad else [THINKING]
    wire = Wire(_message(*blocks), _message(*blocks))
    with pytest.raises(StructuredOutputError) as caught:
        _complete(wire)
    assert len(wire.requests) == 2
    assert caught.value.reason == "not_json"
    failure = describe_llm_error(caught.value)
    assert (failure.category, failure.status_code) == ("invalid_output", 502)
    retry = wire.requests[1]
    assert retry["messages"][0] == USER
    correction = retry["messages"][-1]
    assert correction["role"] == "user"
    assert "not a JSON object" in correction["content"]
    assert "only the JSON object" in correction["content"]
    if bad:
        # The model's own text goes back before the correction (append-only).
        assert retry["messages"][1] == {"role": "assistant", "content": bad}
    else:
        # Nothing to echo (an empty text block is a 400): the correction follows directly.
        assert len(retry["messages"]) == 2
    assert "tools" not in retry and retry["output_config"] == wire.requests[0]["output_config"]


def test_dsml_then_valid_json_succeeds(session, deepseek):
    wire = Wire(_message(_text(DSML)), _message(_text(GOOD)))
    assert _complete(wire) == GOOD
    assert len(wire.requests) == 2


def test_schema_violation_gets_a_retry_naming_it(session, deepseek):
    wire = Wire(_message(THINKING, _text(LIVE_BAD)), _message(_text(GOOD)))
    assert _complete(wire) == GOOD
    _, assistant, correction = wire.requests[1]["messages"]
    assert assistant == {"role": "assistant", "content": json.dumps(LIVE_BAD)}
    assert "$.phases[1]: expected object, got string 'Phase 2: Attention'" in (
        correction["content"])


def test_two_schema_violations_are_invalid_output(session, deepseek):
    wire = Wire(_message(_text(LIVE_BAD)), _message(_text(LIVE_BAD)))
    with pytest.raises(StructuredOutputError) as caught:
        _complete(wire)
    assert caught.value.reason == "schema_mismatch"
    assert "emit_track" in str(caught.value) and "$.phases[1]" in str(caught.value)
    assert describe_llm_error(caught.value).category == "invalid_output"


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_stop_reasons_still_fail_fast(session, deepseek, stop_reason):
    wire = Wire(_message(_text('{"overview": "A'), stop_reason=stop_reason))
    with pytest.raises(StructuredOutputError) as caught:
        _complete(wire)
    assert caught.value.reason == stop_reason and len(wire.requests) == 1


# Every complete_json caller's schema and tool name, with a valid answer.
CALLERS = {
    "curriculum": (CURRICULUM_SCHEMA, "emit_track", GOOD),
    "program_research": (PROGRAM_SCHEMA, "emit_program", {"milestones": [
        {"title": "M", "success_criteria": "s", "depends_on": [], "topics": [{"title": "T"}]}]}),
    "revision": (REVISION_SCHEMA, "emit_revision", {"map_health": "ok", "changes": [
        {"kind": "prune_topic", "why": "stale", "payload": {"link_id": 3}}]}),
    "scout": (SCOUT_SCHEMA, "emit_scout_rank", {"items": [
        {"title": "T", "rationale": "r", "candidate_kind": "frontier",
         "evidence_indexes": [0], "score": 0.5}]}),
    "solution_guard": (GUARD_SCHEMA, GUARD_TOOL, {
        "gives_away_solution": False, "learner_attempted": True, "reason": "hint"}),
}


@pytest.mark.parametrize("caller", sorted(CALLERS))
def test_every_structured_caller_works_in_json_schema_mode(session, deepseek, caller):
    schema, tool_name, answer = CALLERS[caller]
    wire = Wire(_message(THINKING, _text(answer)))
    llm = AnthropicLLMClient(http_client=wire.http_client())
    assert structured_json(llm, "S", [USER], schema=schema, tool_name=tool_name) == answer
    [request] = wire.requests
    assert "tools" not in request
    assert request["output_config"]["format"]["schema"] == to_strict_schema(schema)


# --- the curriculum route, as in the live run --------------------------------------------


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


def test_curriculum_route_succeeds_in_json_schema_mode(session, deepseek):
    topic = _topic(session)
    wire = Wire(_message(_text(GOOD)))
    r = _route_client(session, wire).post(f"/api/topics/{topic.id}/curriculum")
    assert r.status_code == 200, r.text
    assert len(wire.requests) == 1


def test_curriculum_route_dsml_twice_is_a_legible_502(session, deepseek):
    topic = _topic(session)
    wire = Wire(_message(_text(DSML)), _message(_text(DSML)))
    r = _route_client(session, wire).post(f"/api/topics/{topic.id}/curriculum")
    assert r.status_code == 502, r.text
    assert r.json()["category"] == "invalid_output"
