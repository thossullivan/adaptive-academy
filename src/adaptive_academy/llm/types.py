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
