import json
import os
from typing import Any

import httpx
import pydantic
from anthropic import Anthropic, omit

from adaptive_academy.llm.backends import (
    Backend,
    anthropic_base_url,
    api_backend,
    request_extra_body,
)
from adaptive_academy.llm.keys import require_api_key
from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.model_catalog import STRUCTURED_JSON_SCHEMA, capabilities, replayable
from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.schema_check import describe_violations, schema_violations
from adaptive_academy.llm.strict_schema import to_strict_schema
from adaptive_academy.llm.today import today_line
from adaptive_academy.llm.types import (
    NO_RETRY_STOP_REASONS,
    LLMResponse,
    StructuredOutputError,
    ToolCall,
)
from adaptive_academy.llm.usage import check_budget, record_usage
from adaptive_academy.prompts import (
    SCHEMA_RESEND_TEXT,
    SCHEMA_RESEND_TOOL,
    STRUCTURED_JSON_INSTRUCTION,
    STRUCTURED_SCHEMA_RETRY,
    STRUCTURED_TOOL_INSTRUCTION,
    STRUCTURED_TOOL_RETRY,
)


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

    Anthropic: `api_key=` (sent as x-api-key) and an explicit endpoint, api.anthropic.com or a
    non-OpenRouter proxy from ANTHROPIC_BASE_URL. OpenRouter: its base URL and the key as
    `auth_token=` (sent as `Authorization: Bearer`). An Anthropic credential must never reach
    OpenRouter, from either backend. Passing any credential explicitly stops the SDK
    reading ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN (and an explicit base_url beats
    ANTHROPIC_BASE_URL); the header overrides below also neutralise an x-api-key or
    Authorization that ANTHROPIC_CUSTOM_HEADERS would merge in, in whatever spelling.
    tests/test_openrouter_backend.py checks the headers on the wire.
    """
    key = require_api_key(backend)
    if not backend.bearer_auth:
        # Always an explicit endpoint: api.anthropic.com, or a proxy in ANTHROPIC_BASE_URL,
        # never openrouter.ai (see anthropic_base_url).
        return {"api_key": key, "base_url": anthropic_base_url()}
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


def _json_object(text: str) -> dict[str, Any] | None:
    """The JSON object in a text answer (as sent, or inside fences or prose), else None."""
    for candidate in (text, extract_json(text)):
        try:
            data = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(data, dict):
            return data
    return None


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
        check_budget(self._model, reports_cost=self._backend.reports_cost,
                     backend=self._backend.name)

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
        a `strict: true` tool (on every model the catalog says supports it: Claude 4.5 and
        later) and tells the model to answer through the tool. `auto` lets the model reply in
        text instead; that gets one corrective retry (a second, separately recorded call),
        then a StructuredOutputError (a ValueError; the API maps it to a legible 502).

        A model without strict tool use (experimental models, Claude before 4.5) gets the same
        strict-shaped schema without the `strict` flag, so nothing guarantees its answer fits:
        the answer is checked against that schema (llm/schema_check.py), and a mismatch uses
        the same single retry, as an error tool_result naming the first few violations. A
        second mismatch is StructuredOutputError("schema_mismatch"). A strict model's answer
        is not re-checked: the API guarantees it, and the request stays as it was.

        A non-Claude model (structured_output "json_schema") gets no tool at all: see
        _complete_json_schema. Which path runs is the catalog's call (llm/model_catalog.py).
        """
        input_schema = to_strict_schema(schema)
        if self._caps.structured_output == STRUCTURED_JSON_SCHEMA:
            return self._complete_json_schema(system, messages, input_schema, tool_name)
        tool: dict[str, Any] = {
            "name": tool_name,
            "description": "Emit the result as structured data matching the schema.",
            "input_schema": input_schema,
        }
        check_shape = not self._caps.strict_tools
        if not check_shape:
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
        attempt = list(messages)
        failure = "no_tool_use"
        for retries_left in (1, 0):
            self._check_budget()
            resp = self._client.messages.create(messages=attempt, **request,
                                                **request_extra_body(self._backend))
            self._record(resp, "complete_json")
            stop_reason = getattr(resp, "stop_reason", None)
            if stop_reason in NO_RETRY_STOP_REASONS:
                raise StructuredOutputError(stop_reason)
            call = next((b for b in resp.content
                         if b.type == "tool_use" and b.name == tool_name), None)
            if call is None:
                failure = "no_tool_use"
                # Append-only correction: a new user turn, never an edit of earlier history.
                correction = [{"role": "user",
                               "content": STRUCTURED_TOOL_RETRY.format(tool_name=tool_name)}]
            else:
                violations = (schema_violations(call.input, input_schema) if check_shape
                              else [])
                if not violations:
                    return call.input
                failure = "schema_mismatch"
                listed = describe_violations(violations)
                if not retries_left:
                    raise StructuredOutputError(
                        failure, "structured completion did not match its schema after a "
                                 f"corrective retry:\n{listed}")
                correction = self._schema_correction(resp, tool_name, listed)
            attempt = [*messages, *correction]
        raise StructuredOutputError(failure)

    def _complete_json_schema(
        self,
        system: str,
        messages: list[dict[str, Any]],
        schema: dict[str, Any],
        tool_name: str,
    ) -> dict[str, Any]:
        """Structured output without a tool: `output_config.format` carries the strict schema.

        For non-Claude models through OpenRouter, which converts the format for the model's
        provider. The answer is the response's text blocks (thinking blocks are skipped),
        parsed as JSON (fences and surrounding prose tolerated) and checked against the schema.
        Text that isn't a JSON object, or JSON that doesn't fit, gets one corrective retry: the
        model's text, then structured.schema_retry naming what was wrong. A second failure is
        StructuredOutputError ("not_json" or "schema_mismatch"), invalid_output to the API.
        `tool_name` names the answer in errors only; no tool is sent.
        """
        request = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": cached_system(f"{system}\n\n{STRUCTURED_JSON_INSTRUCTION}", self._today),
            "output_config": {"format": {"type": "json_schema", "schema": schema}},
        }
        attempt = list(messages)
        for retries_left in (1, 0):
            self._check_budget()
            # The backend's body fields (OpenRouter's provider privacy preference) still go
            # in extra_body; output_config is a regular SDK parameter.
            resp = self._client.messages.create(messages=attempt, **request,
                                                **request_extra_body(self._backend))
            self._record(resp, "complete_json")
            stop_reason = getattr(resp, "stop_reason", None)
            if stop_reason in NO_RETRY_STOP_REASONS:
                raise StructuredOutputError(stop_reason)
            texts = [b.text for b in resp.content if b.type == "text"]
            text = "".join(texts)
            # Candidates in order: each text block on its own (two complete objects, or a
            # stray brace in prose, would spoil the joined text), the joined text (an object
            # split across blocks), then a tool_use block's input if the model used a tool
            # anyway. The first that fits the schema wins, so an example object in an early
            # prose block can't shadow the real answer; if none fits, the first parseable
            # one's violations go into the retry.
            candidates = [d for d in (*map(_json_object, texts), _json_object(text))
                          if d is not None]
            candidates += [b.input for b in resp.content
                           if b.type == "tool_use" and isinstance(b.input, dict)]
            data = None
            violations: list = []
            for candidate in candidates:
                found = schema_violations(candidate, schema)
                if not found:
                    return candidate
                if data is None:
                    data, violations = candidate, found
            if data is None:
                failure = "not_json"
                begins = (f"it begins {text.strip()[:60]!r}" if text.strip()
                          else "it had no text")
                listed = f"- $: the reply is not a JSON object ({begins})"
            else:
                failure = "schema_mismatch"
                listed = describe_violations(violations)
            if not retries_left:
                raise StructuredOutputError(
                    failure, f"structured answer for {tool_name} was unusable after a "
                             f"corrective retry:\n{listed}")
            # Append-only: the model's own text (an empty text block would be a 400, so none
            # when there was no text), then what was wrong with it.
            echo = [{"role": "assistant", "content": text}] if text.strip() else []
            attempt = [*messages, *echo, {"role": "user", "content": STRUCTURED_SCHEMA_RETRY.format(
                violations=listed, resend=SCHEMA_RESEND_TEXT)}]
        raise AssertionError("unreachable")

    def _schema_correction(self, resp: Any, tool_name: str,
                           listed: str) -> list[dict[str, Any]]:
        """The model's own turn, then an error tool_result for each of its tool calls.

        Every tool_use needs its tool_result in the next user turn, and the turn goes back as
        the model sent it (thinking blocks only for a model that replays them).
        """
        content = replayable(self._model, [content_block_to_param(b) for b in resp.content])
        text = STRUCTURED_SCHEMA_RETRY.format(
            violations=listed, resend=SCHEMA_RESEND_TOOL.format(tool_name=tool_name))
        results = [{"type": "tool_result", "tool_use_id": b["id"], "is_error": True,
                    "content": text}
                   for b in content if b.get("type") == "tool_use"]
        return [{"role": "assistant", "content": content},
                {"role": "user", "content": results}]
