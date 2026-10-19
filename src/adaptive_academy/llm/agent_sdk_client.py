"""An LLMClient backed by the Claude Agent SDK, authenticated via the user's Claude
Pro/Max **subscription** instead of API credits.

Why: the tool is local-first and open-source — each user can run it on their own Claude
plan (the SDK's supported "your own projects" case) instead of paying per-token API credits.
This is a drop-in backend behind the LLMClient Protocol; select it with
`AA_LLM_BACKEND=agent_sdk` (see api/deps.py). Defaults stay on the API-key client.

Auth detail: the SDK subprocess inherits the parent's environment, and a per-call `env`
override can ADD but not REMOVE an inherited `ANTHROPIC_API_KEY` (verified) — if the key is
present the subprocess bills API credits. So agent_sdk mode is **fully subscription-only**:
`create_app()` drops `ANTHROPIC_API_KEY` from the process env once (see api/app.py), and every
SDK-backed client (LLM, Researcher, Anchor) then uses the subscription. No per-call key
juggling, no lock, no race.

Scope: the no-tools structured-completion path (rubric/grade/curriculum/anchors). The Tutor's
tool turns (log_attempt / gated reveal_solution) do not come through here: in agent_sdk mode
the conversations route runs them via `engine/tutor_sdk.py` with in-process SDK tools. The
tool branch in `complete()` is a fallback for any other tool-using caller — a legible
AgentSDKError with no key, a bridge to the API-key client with one.
"""

import asyncio
import os

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    query,
)

from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.types import AgentSDKError, LLMResponse

__all__ = ["AgentSDKLLMClient", "AgentSDKError", "flatten_messages"]


def flatten_messages(messages: list[dict]) -> str:
    """Collapse the messages list into a single prompt string.

    Most calls send one user message (passed through verbatim). A multi-turn history is
    role-prefixed so the single-shot agent turn still sees the conversation.
    """
    if len(messages) == 1:
        return str(messages[0].get("content", ""))
    return "\n\n".join(f"{m.get('role', 'user').upper()}: {m.get('content', '')}"
                       for m in messages)


class AgentSDKLLMClient:
    """LLMClient over the Claude Agent SDK (subscription auth). Sync, single-turn."""

    def __init__(self, role: str = "reasoning"):
        self._role = role
        self._model = get_model(role)

    def _options(self, system: str) -> ClaudeAgentOptions:
        # setting_sources=[] isolates the call from the project's CLAUDE.md/skills so they
        # don't leak into LLM prompts; max_turns=1 + no tools = a single completion.
        return ClaudeAgentOptions(
            model=self._model, system_prompt=system,
            allowed_tools=[], max_turns=1, setting_sources=[])

    async def _run(self, system: str, prompt: str) -> str:
        text = ""
        async for msg in query(prompt=prompt, options=self._options(system)):
            if isinstance(msg, ResultMessage):
                if getattr(msg, "is_error", False):
                    raise AgentSDKError(getattr(msg, "result", "") or "agent SDK error")
                text = getattr(msg, "result", "") or ""
        return text

    def complete(self, system, messages, tools) -> LLMResponse:
        if tools:
            # The Tutor runs its tools via engine/tutor_sdk.py, not here. Any other
            # tool-using caller bridges to the API-key client; with no key set it gets a
            # legible error, not a 500.
            if "ANTHROPIC_API_KEY" not in os.environ:
                raise AgentSDKError(
                    "agent_sdk mode: this tool-use call is not ported to the Agent SDK and "
                    "requires ANTHROPIC_API_KEY.")
            from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
            return AnthropicLLMClient(role=self._role).complete(system, messages, tools)
        # The key is already absent process-wide (create_app dropped it), so the subprocess
        # uses subscription auth — no per-call strip, no lock, parallel-safe.
        text = asyncio.run(self._run(system, flatten_messages(messages)))
        return LLMResponse(text=text, tool_calls=[])
