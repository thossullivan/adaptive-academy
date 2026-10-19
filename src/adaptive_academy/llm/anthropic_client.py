from typing import Any

from anthropic import Anthropic

from adaptive_academy.llm.keys import require_anthropic_api_key
from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.types import LLMResponse, ToolCall


class AnthropicLLMClient:
    """Sync, non-streaming Anthropic client implementing the LLMClient protocol."""

    def __init__(self, role: str = "reasoning", max_tokens: int = 16384):
        # 16384, not 8192/1024: structured outputs (esp. a full curriculum track) overflowed
        # the old ceilings and truncated mid-JSON → "malformed JSON" 502s. The curriculum prompt
        # also bounds scope (6-12 phases), but billing is per output token generated, not per
        # max_tokens, so a high ceiling is free insurance against truncation.
        self._client = Anthropic(api_key=require_anthropic_api_key(), max_retries=3)
        self._model = get_model(role)
        self._max_tokens = max_tokens

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=messages,
            tools=tools,
        )
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
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            messages=messages,
            tools=[tool],
            tool_choice={"type": "tool", "name": tool_name},
        )
        for block in resp.content:
            if block.type == "tool_use" and block.name == tool_name:
                return block.input
        raise ValueError("structured completion returned no tool use")
