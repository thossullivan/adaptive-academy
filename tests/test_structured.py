"""structured_json dispatch: prefer a client's forced-tool `complete_json`, else fall back to
text + tolerant JSON extraction (so clients without structured support, incl. the Agent SDK
client and test fakes, still work)."""

import json

from adaptive_academy.llm.structured import structured_json
from adaptive_academy.llm.types import LLMResponse


class StructuredFake:
    def __init__(self, obj):
        self.obj = obj
        self.called = None

    def complete_json(self, system, messages, *, schema, tool_name):  # noqa: ANN001
        self.called = (schema, tool_name)
        return self.obj


class TextOnlyFake:
    def __init__(self, obj):
        self._obj = obj

    def complete(self, system, messages, tools):  # noqa: ANN001
        return LLMResponse(text="```json\n" + json.dumps(self._obj) + "\n```", tool_calls=[])


def test_uses_complete_json_when_client_supports_it():
    f = StructuredFake({"overview": "x", "phases": []})
    out = structured_json(
        f, "sys", [{"role": "user", "content": "u"}], schema={"type": "object"}, tool_name="emit")
    assert out == {"overview": "x", "phases": []}
    assert f.called == ({"type": "object"}, "emit")  # forwarded schema + tool name


def test_falls_back_to_text_parse_without_structured_support():
    f = TextOnlyFake({"overview": "y", "phases": [{"title": "P1"}]})
    out = structured_json(
        f, "sys", [{"role": "user", "content": "u"}], schema={"type": "object"}, tool_name="emit")
    assert out["overview"] == "y" and out["phases"][0]["title"] == "P1"
