from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    # The assistant turn's content blocks exactly as the API returned them (as dicts), for
    # echoing back in a tool-use loop. Thinking blocks must go back unchanged — signature and
    # empty `thinking` text included — so they can't be rebuilt from `text`/`tool_calls`.
    # None for clients that don't expose raw blocks (scripted fakes, the Agent SDK client).
    raw_content: list[dict[str, Any]] | None = None
    stop_reason: str | None = None


class LLMClient(Protocol):
    def complete(
        self,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
    ) -> LLMResponse: ...


class AgentSDKError(RuntimeError):
    """An Agent SDK call failed (auth/usage/subscription). Lives here (not in
    agent_sdk_client) so the API layer can register a 502 handler for it without
    eagerly importing claude_agent_sdk for default (API-key) users."""


_STRUCTURED_DETAILS = {
    "max_tokens": (
        "The model's answer was too long and was cut off before it finished, so this step "
        "didn't complete. Retrying may help; if it keeps happening, narrow the request."
    ),
    "refusal": (
        "The model declined to produce this output, so this step didn't complete. Retrying "
        "may help, or rephrase the input and try again."
    ),
    "model_context_window_exceeded": (
        "The request was too large for the model's context window, so this step didn't "
        "complete. Retrying with less input (fewer sources, a narrower scope) may help."
    ),
    "no_tool_use": (
        "The model replied without the structured answer this step needs, even after a "
        "corrective retry, so this step didn't complete. Retrying usually helps."
    ),
}


class StructuredOutputError(ValueError):
    """A structured completion (`complete_json`) ended without a usable tool call.

    `reason` is the stop reason that ended it ("max_tokens", "refusal",
    "model_context_window_exceeded") or "no_tool_use" when the model answered in prose
    twice. A ValueError subclass so existing `except ValueError` paths still catch it; the
    API maps it to a legible 502 (api/app.py) with `detail`.
    """

    def __init__(self, reason: str, message: str | None = None):
        self.reason = reason
        if message is None:
            message = ("structured completion returned no tool use" if reason == "no_tool_use"
                       else f"structured completion stopped with stop_reason={reason} "
                            "before a complete tool call")
        super().__init__(message)

    @property
    def detail(self) -> str:
        return _STRUCTURED_DETAILS.get(
            self.reason,
            f"The model's structured answer was unusable ({self.reason}), so this step "
            "didn't complete. Retrying may help.",
        )
