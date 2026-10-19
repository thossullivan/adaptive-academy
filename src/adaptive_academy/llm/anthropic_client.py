from typing import Any

from anthropic import Anthropic

from adaptive_academy.llm.keys import require_anthropic_api_key
from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.types import LLMResponse, ToolCall
from adaptive_academy.llm.usage import BACKEND_ANTHROPIC, check_budget, record_usage


class AnthropicLLMClient:
    """Sync, non-streaming Anthropic client implementing the LLMClient protocol."""

    def __init__(self, role: str = "reasoning", max_tokens: int = 16384):
        # 16384, not 8192/1024: structured outputs (esp. a full curriculum track) overflowed
        # the old ceilings and truncated mid-JSON → "malformed JSON" 502s. The curriculum prompt
        # also bounds scope (6-12 phases), but billing is per output token generated, not per
        # max_tokens, so a high ceiling is free insurance against truncation.
        self._client = Anthropic(api_key=require_anthropic_api_key(), max_retries=3)
        self._role = role
        self._model = get_model(role)
        self._max_tokens = max_tokens

    def _record(self, resp: Any, operation: str) -> None:
        # Recorded as soon as the call returns: it was billed even if parsing fails below.
        record_usage(backend=BACKEND_ANTHROPIC, model=self._model, role=self._role,
                     operation=operation, usage=getattr(resp, "usage", None))

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        check_budget()
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
        self._record(resp, "complete")
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
        return LLMResponse(text="".join(text_parts), tool_calls=tool_calls)

    def complete_json(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any],
        tool_name: str,
    ) -> dict[str, Any]:
        """Forced tool use → guaranteed schema-shaped JSON (no fences, preamble, or shape drift)."""
        tool = {
            "name": tool_name,
            "description": "Emit the result as structured data matching the schema.",
            "input_schema": schema,
        }
        check_budget()
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name},
        )
        self._record(resp, "complete_json")
        for block in resp.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input
        raise ValueError("structured completion returned no tool use")
