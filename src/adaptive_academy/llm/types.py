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
