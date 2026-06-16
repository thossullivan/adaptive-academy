from typing import Any

from adaptive_academy.llm.types import LLMResponse


class ScriptedLLMClient:
    """Test double: returns queued LLMResponses in order, recording calls."""

    def __init__(self, responses: list[LLMResponse]):
        self._responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def complete(self, system, messages, tools) -> LLMResponse:
        self.calls.append({"system": system, "messages": messages, "tools": tools})
        if not self._responses:
            raise AssertionError("ScriptedLLMClient ran out of responses")
        return self._responses.pop(0)
