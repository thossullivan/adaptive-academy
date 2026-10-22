import os
from typing import Any

import httpx
import pydantic
from anthropic import Anthropic, omit

from adaptive_academy.llm.backends import Backend, api_backend, request_extra_body
from adaptive_academy.llm.keys import require_api_key
from adaptive_academy.llm.model_catalog import capabilities, replayable
from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.strict_schema import to_strict_schema
from adaptive_academy.llm.today import today_line
from adaptive_academy.llm.types import (
    NO_RETRY_STOP_REASONS,
    LLMResponse,
    StructuredOutputError,
    ToolCall,
)
from adaptive_academy.llm.usage import check_budget, record_usage
from adaptive_academy.prompts import STRUCTURED_TOOL_INSTRUCTION, STRUCTURED_TOOL_RETRY


# Prompt caching (claude-api skill, shared/prompt-caching.md). The prefix renders tools ->
# system -> messages, and a breakpoint on the last stable system block caches tools + system
# together. Today's date goes in its own block AFTER that breakpoint, so a new day leaves the
# tools + system cache entry valid; the conversation cache (the automatic breakpoint, which
# sits after the date) does start over on a new day. A prefix shorter than the model's
# minimum (512 tokens on Sonnet/Haiku 5.5, 1024 on Sonnet 4.6, 4096 on Haiku 4.5) is silently
# not cached: no error and no write charge, so the marker is sent regardless and a short
# prompt just doesn't cache. Default 5-minute TTL; llm/usage.py prices the cache reads and
# writes each response reports.
EPHEMERAL = {"type": "ephemeral"}


def cached_system(system: str, date_line: str) -> list[dict[str, Any]]:
    """System blocks: the stable text with a cache breakpoint, then the date (no marker)."""
    return [
        {"type": "text", "text": system, "cache_control": EPHEMERAL},
        {"type": "text", "text": date_line},
    ]


_CREDENTIAL_HEADERS = ("x-api-key", "authorization")


def sdk_client_kwargs(backend: Backend) -> dict[str, Any]:
    """Credential and endpoint arguments for `Anthropic(...)` on this backend.

    Anthropic: `api_key=` (sent as x-api-key) and the SDK's default endpoint. OpenRouter: its
    base URL and the key as `auth_token=` (sent as `Authorization: Bearer`). An Anthropic
    credential must never reach OpenRouter. Passing any credential explicitly stops the SDK
    reading ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN (and an explicit base_url beats
    ANTHROPIC_BASE_URL); the header overrides below also neutralise an x-api-key or
    Authorization that ANTHROPIC_CUSTOM_HEADERS would merge in, in whatever spelling.
    tests/test_openrouter_backend.py checks the headers on the wire.
    """
    key = require_api_key(backend)
    if not backend.bearer_auth:
        return {"api_key": key}
    headers: dict[str, Any] = {"X-Api-Key": omit}
    for line in os.environ.get("ANTHROPIC_CUSTOM_HEADERS", "").split("\n"):
        name = line.split(":", 1)[0].strip()
        if name.lower() in _CREDENTIAL_HEADERS:
            # The SDK's own Authorization (from auth_token) is spelled exactly so; keep that
            # one ours and drop every other spelling, so no second value is merged in.
            headers[name] = f"Bearer {key}" if name == "Authorization" else omit
    return {"auth_token": key, "base_url": backend.base_url, "default_headers": headers}


def content_block_to_param(block: Any) -> dict[str, Any]:
    """One response content block as a request param, unchanged.

    Mirrors how the SDK serialises a response block passed back in `messages` (only the fields
    the API actually sent, JSON mode, API names), so thinking blocks keep their signature and
    their (possibly empty) text exactly as received.
    """
    if isinstance(block, pydantic.BaseModel):
        return block.model_dump(exclude_unset=True, mode="json", by_alias=True)
    if isinstance(block, dict):
        return dict(block)
    return dict(vars(block))


class AnthropicLLMClient:
    """Sync, non-streaming Anthropic SDK client implementing the LLMClient protocol.

    Works unchanged on claude-sonnet-5-5 / claude-haiku-5-5 (the defaults) and on the older
    claude-sonnet-4-6 / claude-haiku-4-5: no sampling params, no prefill, no `thinking` field
    (each model runs its default — adaptive on the 5.5 models), no forced tool_choice, and
    responses are read by block type so `thinking` blocks are skipped.

    The backend (llm/backends.py) picks the endpoint and credential: the Anthropic API, or
    OpenRouter's Anthropic-format Messages endpoint. Per-model differences (strict tools,
    thinking replay) come from llm/model_catalog.py.
    """

    def __init__(
        self,
        role: str = "reasoning",
        max_tokens: int = 20_000,
        *,
        http_client: httpx.Client | None = None,
    ):
        # max_tokens covers thinking + text on models that think by default (Sonnet/Haiku 5.5),
        # and thinking tokens bill as output only when generated — the ceiling itself is free
        # insurance against a structured answer (e.g. a full curriculum track) being cut off
        # mid-JSON. 20k stays under the SDK's non-streaming limit (~21.3k, the 10-minute rule).
        # Known limit: the SDK's own retries (after a read timeout or dropped connection)
        # happen inside messages.create and their usage is never reported back, so a
        # retried call is recorded (and counted against the daily limit) only once.
        # `http_client` is a test seam: tests/test_response_replay.py passes an httpx.Client
        # on a MockTransport to replay API responses through the real SDK, and
        # scripts/record_response_fixtures.py one with a capture hook. The app passes
        # nothing and gets the SDK's default client.
        self._backend = api_backend()
        self._client = Anthropic(**sdk_client_kwargs(self._backend), max_retries=3,
                                 http_client=http_client)
        self._role = role
        self._model = get_model(role)
        self._caps = capabilities(self._model)
        self._max_tokens = max_tokens
        # The date is fixed for this client's life. Thinking blocks echoed in a tool loop
        # are bound to the system prompt they were made under, so a loop that crossed
        # midnight with a fresh date would be rejected (400). Clients are built per request
        # (api/deps.py), so the next request gets the new day.
        self._today = today_line()

    def _record(self, resp: Any, operation: str) -> None:
        # Recorded as soon as the call returns: it was billed even if parsing fails below.
        record_usage(backend=self._backend.name, model=self._model, role=self._role,
                     operation=operation, usage=getattr(resp, "usage", None))

    def _check_budget(self) -> None:
        check_budget(self._model, reports_cost=self._backend.reports_cost)

    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse:
        request: dict[str, Any] = {}
        if tools or len(messages) > 1:
            # A conversation (the tutor's tool loop and turns, the roleplay persona): top-level
            # automatic caching puts a breakpoint on the last block and moves it forward each
            # request, so the next step or turn reads everything before it from cache. Not on
            # a one-off single message: the write premium would buy nothing.
            request["cache_control"] = EPHEMERAL
        self._check_budget()
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=cached_system(system, self._today),
            messages=messages,
            tools=tools,
            **request,
            **request_extra_body(self._backend),
        )
        self._record(resp, "complete")
        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in resp.content:
            # By type, never by position: thinking blocks (and, on Sonnet 5.5, progress
            # updates between tool calls) arrive as `thinking` and are not reply text.
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            # Echoed back in a tool loop: thinking blocks stay for models that replay them.
            raw_content=replayable(self._model,
                                   [content_block_to_param(b) for b in resp.content]),
            stop_reason=getattr(resp, "stop_reason", None),
        )

    def complete_json(
        self,
        system: str,
        messages: list[dict[str, Any]],
        *,
        schema: dict[str, Any],
        tool_name: str,
    ) -> dict[str, Any]:
        """Strict tool use → schema-valid JSON (no fences, preamble, or shape drift).

        Forced tool_choice is a 400 on Claude Sonnet 5.5, so this uses tool_choice=auto with
        a `strict: true` tool (on every model the catalog says supports it: all Claude models)
        and tells the model to answer through the tool. `auto` lets the model reply in text
        instead; that gets one corrective retry (a second, separately recorded call), then a
        StructuredOutputError (a ValueError; the API maps it to a legible 502). An
        experimental model gets the same strict-shaped schema without the `strict` flag.
        """
        tool: dict[str, Any] = {
            "name": tool_name,
            "description": "Emit the result as structured data matching the schema.",
            "input_schema": to_strict_schema(schema),
        }
        if self._caps.strict_tools:
            tool["strict"] = True
        request = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            # Tools + system are cached; the corrective retry re-sends them unchanged. No
            # automatic breakpoint: the user message is one-off and a retry is rare.
            "system": cached_system(
                f"{system}\n\n{STRUCTURED_TOOL_INSTRUCTION.format(tool_name=tool_name)}",
                self._today),
            "tools": [tool],
            "tool_choice": {"type": "auto", "disable_parallel_tool_use": True},
        }
        attempts = [
            list(messages),
            # Append-only correction: a new user turn, never an edit of earlier history.
            [*messages, {"role": "user",
                         "content": STRUCTURED_TOOL_RETRY.format(tool_name=tool_name)}],
        ]
        for attempt in attempts:
            self._check_budget()
            resp = self._client.messages.create(messages=attempt, **request,
                                                **request_extra_body(self._backend))
            self._record(resp, "complete_json")
            stop_reason = getattr(resp, "stop_reason", None)
            if stop_reason in NO_RETRY_STOP_REASONS:
                raise StructuredOutputError(stop_reason)
            for block in resp.content:
                if block.type == "tool_use" and block.name == tool_name:
                    return block.input
        raise StructuredOutputError("no_tool_use")
