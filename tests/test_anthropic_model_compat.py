"""The API-key LLM path works on the Claude 5.5 defaults (claude-sonnet-5-5 / claude-haiku-5-5)
and on the older models a user can still configure (claude-sonnet-4-6 / claude-haiku-4-5).

Grounded in the Sonnet 5.5 migration guide and the thinking / strict-tool-use docs:
- forced tool_choice ("tool"/"any") is a 400 on Sonnet 5.5 → `auto` + `strict: true` + a prompt
  instruction (strict tool use is supported on all four models, so this is one code path);
- strict tools need the supported JSON Schema subset, with additionalProperties false on every
  object;
- thinking is on by default, so responses can carry `thinking` blocks: read content by type,
  and pass thinking blocks back unchanged (signature included) inside a tool-use loop;
- no sampling params, no prefill, no thinking budget / disabled thinking.

No network: the Anthropic SDK class is replaced by a fake whose `messages.create` returns
queued canned responses built from the real SDK content-block types.
"""

import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from anthropic.types import (
    ServerToolUseBlock,
    TextBlock,
    ThinkingBlock,
    ToolUseBlock,
    WebSearchToolResultBlock,
)
from sqlmodel import select

from adaptive_academy.engine.curriculum import CURRICULUM_SCHEMA
from adaptive_academy.engine.program_research import PROGRAM_SCHEMA
from adaptive_academy.engine.revision import REVISION_SCHEMA
from adaptive_academy.engine.solution_guard import GUARD_SCHEMA
from adaptive_academy.llm import usage
from adaptive_academy.llm.researcher_types import SearchBrief
from adaptive_academy.llm.strict_schema import to_strict_schema
from adaptive_academy.llm.structured import SCOUT_SCHEMA
from adaptive_academy.models import LLMUsage

SRC = Path(__file__).resolve().parents[1] / "src" / "adaptive_academy"

# Every schema a real caller passes to structured_json / complete_json. The completeness test
# below fails if a caller is added without being audited here.
REAL_SCHEMAS = {
    "CURRICULUM_SCHEMA": CURRICULUM_SCHEMA,
    "GUARD_SCHEMA": GUARD_SCHEMA,
    "PROGRAM_SCHEMA": PROGRAM_SCHEMA,
    "REVISION_SCHEMA": REVISION_SCHEMA,
    "SCOUT_SCHEMA": SCOUT_SCHEMA,
}

SIG = "EqQBCgIYAhIM1gbcDa9GJwZA2b3hGgxBdjrkzLoky3dl1pkiMOYds="


# --- fakes ----------------------------------------------------------------------------


def _usage(**kw):
    base = dict(input_tokens=100, output_tokens=50, cache_creation_input_tokens=0,
                cache_read_input_tokens=0, server_tool_use=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _resp(*blocks, stop_reason="end_turn", **usage_kw):
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason,
                           usage=_usage(**usage_kw))


def _thinking(text=""):
    # Sonnet/Haiku 5.5 default display is "omitted": empty thinking text plus a signature.
    return ThinkingBlock(type="thinking", thinking=text, signature=SIG)


def _text(text):
    return TextBlock(type="text", text=text)


def _tool_use(name, inp, id_="toolu_01"):
    return ToolUseBlock(type="tool_use", id=id_, name=name, input=inp)


def _fake_anthropic(monkeypatch, module, responses, calls):
    queue = list(responses)

    class _Messages:
        def create(self, **kw):
            calls.append(kw)
            if not queue:
                raise AssertionError("fake Anthropic ran out of responses")
            return queue.pop(0)

    class _FakeAnthropic:
        def __init__(self, *a, **kw):
            self.messages = _Messages()

    monkeypatch.setattr(f"adaptive_academy.llm.{module}.Anthropic", _FakeAnthropic)


@pytest.fixture
def api_key(monkeypatch):
    monkeypatch.delenv("AA_LLM_BACKEND", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-not-a-real-key")


def _rows(session):
    session.expire_all()
    return session.exec(select(LLMUsage).order_by(LLMUsage.id)).all()


_FORBIDDEN_REQUEST_KEYS = {"temperature", "top_p", "top_k", "thinking"}


def _assert_request_is_55_safe(kw):
    assert not (_FORBIDDEN_REQUEST_KEYS & set(kw)), kw.keys()
    tc = kw.get("tool_choice")
    assert tc is None or tc.get("type") in ("auto", "none"), tc
    # No assistant prefill: the conversation must end with a user turn.
    assert kw["messages"][-1]["role"] == "user"


SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}, "n": {"type": "integer", "minimum": 0}},
    "required": ["answer"],
}


# --- complete_json: auto + strict + instruction ----------------------------------------


def test_complete_json_sends_auto_and_strict_tool_with_instruction(session, api_key,
                                                                    monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client",
                    [_resp(_thinking(), _tool_use("emit", {"answer": "ok"}),
                           stop_reason="tool_use")], calls)
    out = AnthropicLLMClient().complete_json(
        "SYS", [{"role": "user", "content": "x"}], schema=SCHEMA, tool_name="emit")
    assert out == {"answer": "ok"}

    [kw] = calls
    _assert_request_is_55_safe(kw)
    assert kw["tool_choice"]["type"] == "auto"  # never {"type": "tool"} / {"type": "any"}
    [tool] = kw["tools"]
    assert tool["name"] == "emit"
    assert tool["strict"] is True
    assert tool["input_schema"]["additionalProperties"] is False
    # `minimum` is not in the strict subset; it must not be sent as a keyword.
    assert "minimum" not in tool["input_schema"]["properties"]["n"]
    # The model is told, in the request, to answer by calling the tool.
    # (system is a list of text blocks: the cached stable part, then today's date.)
    stable = kw["system"][0]["text"]
    assert stable.startswith("SYS")
    assert "emit" in stable[len("SYS"):]
    # The caller's schema is not mutated by the strict transform.
    assert "additionalProperties" not in SCHEMA
    assert SCHEMA["properties"]["n"]["minimum"] == 0


def test_complete_json_ignores_thinking_and_text_blocks(session, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client",
                    [_resp(_thinking(), _text("Here you go."), _thinking("note"),
                           _tool_use("emit", {"answer": "42"}), stop_reason="tool_use")],
                    calls)
    out = AnthropicLLMClient().complete_json(
        "s", [{"role": "user", "content": "x"}], schema=SCHEMA, tool_name="emit")
    assert out == {"answer": "42"}


def test_complete_json_retries_once_when_model_answers_in_text(session, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", [
        _resp(_thinking(), _text('{"answer": "in prose"}')),
        _resp(_thinking(), _tool_use("emit", {"answer": "via tool"}), stop_reason="tool_use"),
    ], calls)
    original = [{"role": "user", "content": "x"}]
    out = AnthropicLLMClient().complete_json("s", original, schema=SCHEMA, tool_name="emit")
    assert out == {"answer": "via tool"}

    assert len(calls) == 2
    first, retry = calls
    _assert_request_is_55_safe(retry)
    # The retry appends a corrective user turn naming the tool; it never edits history.
    assert retry["messages"][: len(original)] == original
    assert len(retry["messages"]) == len(original) + 1
    assert retry["messages"][-1]["role"] == "user"
    assert "emit" in str(retry["messages"][-1]["content"])
    assert retry["tools"] == first["tools"] and retry["system"] == first["system"]
    assert original == [{"role": "user", "content": "x"}]  # caller's list untouched
    # A retry is a second billed call: two usage rows.
    assert [r.operation for r in _rows(session)] == ["complete_json", "complete_json"]


def test_complete_json_raises_after_one_failed_retry(session, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client",
                    [_resp(_text("prose")), _resp(_thinking(), _text("still prose"))], calls)
    with pytest.raises(ValueError, match="no tool use"):
        AnthropicLLMClient().complete_json(
            "s", [{"role": "user", "content": "x"}], schema=SCHEMA, tool_name="emit")
    assert len(calls) == 2
    assert len(_rows(session)) == 2


def test_complete_json_retry_respects_the_daily_budget(session, api_key, monkeypatch):
    # The budget check runs before every API-key call, the corrective retry included.
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    checks: list = []
    monkeypatch.setattr("adaptive_academy.llm.anthropic_client.check_budget",
                        lambda model=None, reports_cost=False: checks.append(model))
    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client",
                    [_resp(_text("prose")), _resp(_tool_use("emit", {"answer": "a"}))], calls)
    AnthropicLLMClient().complete_json(
        "s", [{"role": "user", "content": "x"}], schema=SCHEMA, tool_name="emit")
    assert checks == ["claude-sonnet-5-5"] * 2  # each check is for the call's model


@pytest.mark.parametrize("stop_reason", ["max_tokens", "refusal"])
def test_complete_json_does_not_retry_truncation_or_refusal(session, api_key, monkeypatch,
                                                            stop_reason):
    # A truncated or refused answer would fail the same way again: fail fast with a clear
    # error instead of paying for a second call.
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client",
                    [_resp(_thinking(), stop_reason=stop_reason)], calls)
    with pytest.raises(ValueError, match=stop_reason):
        AnthropicLLMClient().complete_json(
            "s", [{"role": "user", "content": "x"}], schema=SCHEMA, tool_name="emit")
    assert len(calls) == 1
    assert len(_rows(session)) == 1


def test_complete_json_rejects_a_truncated_tool_call(session, api_key, monkeypatch):
    # stop_reason max_tokens with a (partial) tool_use block: the input can't be trusted.
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client",
                    [_resp(_tool_use("emit", {"answer": "trunc"}), stop_reason="max_tokens")],
                    calls)
    with pytest.raises(ValueError, match="max_tokens"):
        AnthropicLLMClient().complete_json(
            "s", [{"role": "user", "content": "x"}], schema=SCHEMA, tool_name="emit")


def test_max_tokens_ceilings_leave_room_for_thinking_without_streaming(api_key):
    # max_tokens covers thinking + text on the 5.5 models. Non-streaming SDK calls refuse
    # max_tokens above ~21,333 (the 10-minute rule), so stay under it.
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient

    assert 16384 < AnthropicLLMClient()._max_tokens <= 21_333
    assert 8192 < AnthropicResearcherClient()._max_tokens <= 21_333


# --- complete: thinking blocks ---------------------------------------------------------


def test_complete_reads_by_type_and_carries_raw_content(session, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", [_resp(
        _thinking(), _text("Let me log that."), _thinking("progress note"),
        _tool_use("log_attempt", {"summary": "tried"}), stop_reason="tool_use")], calls)
    resp = AnthropicLLMClient().complete("s", [{"role": "user", "content": "x"}], tools=[])

    _assert_request_is_55_safe(calls[0])
    assert resp.text == "Let me log that."
    assert [c.name for c in resp.tool_calls] == ["log_attempt"]
    assert resp.raw_content == [
        {"type": "thinking", "thinking": "", "signature": SIG},
        {"type": "text", "text": "Let me log that."},
        {"type": "thinking", "thinking": "progress note", "signature": SIG},
        {"type": "tool_use", "id": "toolu_01", "name": "log_attempt",
         "input": {"summary": "tried"}},
    ]


def test_complete_raw_content_works_with_plain_namespace_blocks(session, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client",
                    [SimpleNamespace(content=[SimpleNamespace(type="text", text="hi")])], calls)
    resp = AnthropicLLMClient().complete("s", [{"role": "user", "content": "x"}], tools=[])
    assert resp.text == "hi"
    assert resp.raw_content == [{"type": "text", "text": "hi"}]


# --- tutor loop: thinking blocks echoed unchanged ---------------------------------------


def _seed_convo(session):
    from adaptive_academy.models import Concept, Conversation, KnowledgeEstimate, Topic, Track

    topic = Topic(title="LLMs")
    session.add(topic)
    session.commit()
    track = Track(topic_id=topic.id, title="Core")
    session.add(track)
    session.commit()
    concept = Concept(track_id=track.id, name="self-attention")
    session.add(concept)
    session.commit()
    session.add(KnowledgeEstimate(concept_id=concept.id, level="high"))
    convo = Conversation(topic_id=topic.id, concept_id=concept.id)
    session.add(convo)
    session.commit()
    return convo


def test_tutor_loop_echoes_raw_assistant_blocks_unchanged(session):
    from adaptive_academy.engine.tutor import run_tutor_turn
    from adaptive_academy.llm.scripted_client import ScriptedLLMClient
    from adaptive_academy.llm.types import LLMResponse, ToolCall

    raw = [
        {"type": "thinking", "thinking": "", "signature": SIG},
        {"type": "tool_use", "id": "t1", "name": "log_attempt", "input": {"summary": "QK^T"}},
    ]
    llm = ScriptedLLMClient([
        LLMResponse(tool_calls=[ToolCall(id="t1", name="log_attempt",
                                         input={"summary": "QK^T"})], raw_content=raw),
        LLMResponse(text="Good attempt. What normalises the scores?"),
    ])
    run_tutor_turn(session, _seed_convo(session), "attention is softmax(QK^T)V", llm)

    second = llm.calls[1]["messages"]
    assistant, results = second[-2], second[-1]
    assert assistant == {"role": "assistant", "content": raw}
    assert assistant["content"][0]["signature"] == SIG
    assert results["role"] == "user"
    assert results["content"][0]["tool_use_id"] == "t1"


def test_tutor_loop_end_to_end_with_real_client_preserves_thinking(session, api_key,
                                                                   monkeypatch):
    from adaptive_academy.engine.tutor import run_tutor_turn
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client", [
        _resp(_thinking(), _tool_use("log_attempt", {"summary": "QK^T"}, id_="toolu_9"),
              stop_reason="tool_use"),
        _resp(_thinking(), _text("Nice. Why divide by sqrt(d_k)?")),
    ], calls)
    result = run_tutor_turn(session, _seed_convo(session), "softmax(QK^T)V",
                            AnthropicLLMClient())
    assert result.reply == "Nice. Why divide by sqrt(d_k)?"

    assert len(calls) == 2
    for kw in calls:
        _assert_request_is_55_safe(kw)
    echoed = calls[1]["messages"][-2]
    assert echoed["role"] == "assistant"
    assert echoed["content"] == [
        {"type": "thinking", "thinking": "", "signature": SIG},
        {"type": "tool_use", "id": "toolu_9", "name": "log_attempt",
         "input": {"summary": "QK^T"}},
    ]
    # Append-only: the second request starts with exactly the first request's messages.
    first_msgs = calls[0]["messages"]
    assert calls[1]["messages"][: len(first_msgs)] == first_msgs
    assert calls[1]["system"] == calls[0]["system"]
    assert calls[1]["tools"] == calls[0]["tools"]


# --- researcher -------------------------------------------------------------------------


def test_researcher_parses_text_with_thinking_and_search_blocks(session, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient

    payload = '[{"title": "T", "url": "https://example.org/a", "tier": 1}]'
    search = ServerToolUseBlock(type="server_tool_use", id="srvtoolu_1", name="web_search",
                                input={"query": "q"})
    result = WebSearchToolResultBlock(type="web_search_tool_result", tool_use_id="srvtoolu_1",
                                      content=[])
    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_researcher", [_resp(
        _thinking(), search, result, _thinking("progress"), _text(payload),
        server_tool_use=SimpleNamespace(web_search_requests=2))], calls)
    out = AnthropicResearcherClient().search(SearchBrief(angle="a", query="q"))

    assert [s.url for s in out] == ["https://example.org/a"]
    [kw] = calls
    _assert_request_is_55_safe(kw)
    assert kw["tools"][0]["type"] == "web_search_20250305"
    [row] = _rows(session)
    assert row.web_search_requests == 2


def _search_block(id_="srvtoolu_1"):
    return ServerToolUseBlock(type="server_tool_use", id=id_, name="web_search",
                              input={"query": "q"})


def test_researcher_continues_a_paused_turn_until_it_finishes(session, api_key, monkeypatch):
    # Server tools docs: on stop_reason "pause_turn", re-send the request with the paused
    # assistant content appended, same tools, and repeat while it keeps pausing.
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient

    checks: list = []
    monkeypatch.setattr("adaptive_academy.llm.anthropic_researcher.check_budget",
                        lambda model=None, reports_cost=False: checks.append(model))
    payload = '[{"title": "T", "url": "https://example.org/final"}]'
    first = _resp(_thinking(), _text("Searching."), _search_block("srvtoolu_1"),
                  stop_reason="pause_turn",
                  server_tool_use=SimpleNamespace(web_search_requests=1))
    second = _resp(_search_block("srvtoolu_2"), stop_reason="pause_turn",
                   server_tool_use=SimpleNamespace(web_search_requests=2))
    final = _resp(_thinking(), _text(payload), stop_reason="end_turn",
                  server_tool_use=SimpleNamespace(web_search_requests=1))
    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_researcher", [first, second, final], calls)

    out = AnthropicResearcherClient().search(SearchBrief(angle="ang", query="q"))
    assert [(s.url, s.angle) for s in out] == [("https://example.org/final", "ang")]

    assert len(calls) == 3 and checks == ["claude-sonnet-5-5"] * 3
    user = {"role": "user", "content": "q"}
    assert calls[0]["messages"] == [user]
    assert calls[1]["messages"] == [user, {"role": "assistant", "content": [
        {"type": "thinking", "thinking": "", "signature": SIG},
        {"type": "text", "text": "Searching."},
        {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search",
         "input": {"query": "q"}},
    ]}]
    # A second pause extends the same (still open) assistant turn.
    assert calls[2]["messages"][0] == user
    assert calls[2]["messages"][1]["role"] == "assistant"
    assert calls[2]["messages"][1]["content"][-1]["id"] == "srvtoolu_2"
    assert len(calls[2]["messages"]) == 2
    for kw in calls:
        assert kw["tools"] == calls[0]["tools"] and kw["system"] == calls[0]["system"]
        assert not (_FORBIDDEN_REQUEST_KEYS & set(kw))
    rows = _rows(session)
    assert [r.operation for r in rows] == ["research_search"] * 3
    assert sum(r.web_search_requests for r in rows) == 4


def test_researcher_caps_continuations(session, api_key, monkeypatch):
    from adaptive_academy.llm.anthropic_researcher import (
        MAX_PAUSE_CONTINUATIONS,
        AnthropicResearcherClient,
    )

    assert MAX_PAUSE_CONTINUATIONS == 3
    paused = [_resp(_search_block(f"srvtoolu_{i}"), stop_reason="pause_turn")
              for i in range(10)]
    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_researcher", paused, calls)
    out = AnthropicResearcherClient().search(SearchBrief(angle="a", query="q"))
    assert out == []
    assert len(calls) == 1 + MAX_PAUSE_CONTINUATIONS
    assert len(_rows(session)) == 1 + MAX_PAUSE_CONTINUATIONS


def test_researcher_falls_back_to_earlier_text_if_the_final_turn_has_none(session, api_key,
                                                                          monkeypatch):
    from adaptive_academy.llm.anthropic_researcher import AnthropicResearcherClient

    payload = '[{"title": "T", "url": "https://example.org/early"}]'
    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_researcher", [
        _resp(_text(payload), _search_block(), stop_reason="pause_turn"),
        _resp(_thinking(), stop_reason="end_turn"),
    ], calls)
    out = AnthropicResearcherClient().search(SearchBrief(angle="a", query="q"))
    assert [s.url for s in out] == ["https://example.org/early"]


# --- schema audit -----------------------------------------------------------------------

# Keywords outside the strict-tool / structured-outputs JSON Schema subset ("JSON Schema
# limitations": numerical constraints, string length constraints, array constraints beyond
# minItems 0/1, and additionalProperties other than false).
_UNSUPPORTED = {
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minLength", "maxLength", "maxItems", "uniqueItems", "contains", "minContains",
    "maxContains", "minProperties", "maxProperties", "patternProperties",
    "propertyNames", "dependentRequired", "dependentSchemas", "if", "then", "else", "not",
    "oneOf",
}
_FORMATS = {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4",
            "ipv6", "uuid"}


def _walk(node, path="$"):
    """Yield (path, subschema) for every schema node."""
    if not isinstance(node, dict):
        return
    yield path, node
    for key, sub in (node.get("properties") or {}).items():
        yield from _walk(sub, f"{path}.{key}")
    if "items" in node:
        yield from _walk(node["items"], f"{path}[]")
    for key in ("anyOf", "allOf"):
        for i, sub in enumerate(node.get(key) or []):
            yield from _walk(sub, f"{path}.{key}[{i}]")
    for name, sub in (node.get("$defs") or {}).items():
        yield from _walk(sub, f"$defs.{name}")


def _problems(schema):
    problems = []
    optional = 0
    unions = 0
    for path, node in _walk(schema):
        bad = _UNSUPPORTED & set(node)
        if bad:
            problems.append(f"{path}: unsupported {sorted(bad)}")
        if node.get("type") == "object":
            if node.get("additionalProperties") is not False:
                problems.append(f"{path}: additionalProperties must be false")
            props = node.get("properties") or {}
            if not props:
                problems.append(f"{path}: object without properties (strict would force {{}})")
            required = set(node.get("required") or [])
            if not required <= set(props):
                problems.append(f"{path}: required names unknown properties")
            optional += len(set(props) - required)
        if "additionalProperties" in node and node["additionalProperties"] is not False:
            problems.append(f"{path}: additionalProperties must be false")
        if "minItems" in node and node["minItems"] not in (0, 1):
            problems.append(f"{path}: minItems must be 0 or 1")
        if "format" in node and node["format"] not in _FORMATS:
            problems.append(f"{path}: unsupported format {node['format']}")
        if "anyOf" in node or isinstance(node.get("type"), list):
            unions += 1
        for value in node.get("enum") or []:
            if isinstance(value, (dict, list)):
                problems.append(f"{path}: complex enum value")
    # Documented compile limits: 24 optional parameters, 16 union-typed parameters.
    if optional > 24:
        problems.append(f"{optional} optional parameters (> 24)")
    if unions > 16:
        problems.append(f"{unions} union-typed parameters (> 16)")
    return problems


@pytest.mark.parametrize("name", sorted(REAL_SCHEMAS))
def test_every_real_schema_is_strict_compliant_as_sent(name):
    sent = to_strict_schema(REAL_SCHEMAS[name])
    assert _problems(sent) == []


def test_audited_schema_list_covers_every_structured_caller():
    used = set()
    for path in SRC.rglob("*.py"):
        used |= set(re.findall(r"\bschema=([A-Z_]+_SCHEMA)\b", path.read_text()))
    assert used == set(REAL_SCHEMAS)


def test_to_strict_schema_rejects_an_open_object():
    # Strict mode would force an open object to be `{}` and silently drop its content.
    with pytest.raises(ValueError, match="properties"):
        to_strict_schema({"type": "object", "properties": {"p": {"type": "object"}}})


def test_revision_payload_schema_covers_every_field_the_engine_reads():
    payload = REVISION_SCHEMA["properties"]["changes"]["items"]["properties"]["payload"]
    fields = set(payload["properties"])
    assert {"milestone_id", "link_id", "after_milestone_id", "title", "success_criteria",
            "topics"} <= fields
    topic = payload["properties"]["topics"]["items"]
    assert {"title", "why"} <= set(topic["properties"])


def test_strict_schema_keeps_dropped_constraints_as_description_hints():
    sent = to_strict_schema(SCOUT_SCHEMA)
    items = sent["properties"]["items"]
    assert "maxItems" not in items
    assert "5" in items.get("description", "")


def test_usage_rows_unaffected_without_bind(api_key, monkeypatch):
    # Sanity: the compat changes don't make recording mandatory.
    from adaptive_academy.llm.anthropic_client import AnthropicLLMClient

    assert usage.get_usage_bind() is None
    calls: list = []
    _fake_anthropic(monkeypatch, "anthropic_client",
                    [_resp(_tool_use("emit", {"answer": "a"}), stop_reason="tool_use")], calls)
    assert AnthropicLLMClient().complete_json(
        "s", [{"role": "user", "content": "x"}], schema=SCHEMA, tool_name="emit") == {
        "answer": "a"}
