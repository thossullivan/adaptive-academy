"""An LLMClient backed by the Claude Agent SDK, authenticated via the user's Claude
Pro/Max **subscription** instead of API credits.

Why: the tool is local-first and open-source — each user can run it on their own Claude
plan (the SDK's supported "your own projects" case) instead of paying per-token API credits.
This is a drop-in backend behind the LLMClient Protocol; select it with
`AA_LLM_BACKEND=agent_sdk` (see api/deps.py). Defaults stay on the API-key client.

Auth detail: the SDK spawns the Claude Code engine as a subprocess that **inherits the
parent's environment**, and a per-call `env` override can ADD but not REMOVE an inherited
`ANTHROPIC_API_KEY` (verified). If the key is present the subprocess bills API credits, so
we pop it from `os.environ` for the duration of the call (under a lock) and restore it
after — leaving the still-API-key Researcher/Anchor clients (which capture their key at
construction) unaffected.

Scope (spike): the no-tools structured-completion path (rubric/grade/curriculum/anchors).
Tool calls (the Tutor's gated reveal_solution) and web-search fan-out are follow-ups.
"""

import asyncio
import os
import threading

from claude_agent_sdk import (
    ClaudeAgentOptions,
    ResultMessage,
    query,
)

from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.types import LLMResponse

_ENV_LOCK = threading.Lock()


class AgentSDKError(RuntimeError):
    """The Agent SDK returned an error result (e.g. auth/usage failure)."""


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
            # Tool-use turns (the Tutor's gated reveal_solution) aren't ported to the SDK
            # yet; bridge them to the API-key client so agent_sdk mode stays fully usable.
            from adaptive_academy.llm.anthropic_client import AnthropicLLMClient
            return AnthropicLLMClient(role=self._role).complete(system, messages, tools)
        prompt = flatten_messages(messages)
        # Strip ANTHROPIC_API_KEY for this subprocess so it uses subscription auth, then
        # restore so other (API-key) clients keep working. Lock = no concurrent strip race.
        with _ENV_LOCK:
            saved = os.environ.pop("ANTHROPIC_API_KEY", None)
            try:
                text = asyncio.run(self._run(system, prompt))
            finally:
                if saved is not None:
                    os.environ["ANTHROPIC_API_KEY"] = saved
        return LLMResponse(text=text, tool_calls=[])
