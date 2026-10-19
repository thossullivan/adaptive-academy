"""A ResearcherClient backed by the Claude Agent SDK's built-in WebSearch tool, on the
user's Claude subscription (no API credits).

Drop-in for AnthropicResearcherClient behind the ResearcherClient Protocol; selected by
`AA_LLM_BACKEND=agent_sdk`. Reuses the API researcher's system prompt and `parse_sources_json`
so the output is the same RawSource shape the fan-out orchestrator already expects.

agent_sdk mode is fully subscription-only (create_app drops ANTHROPIC_API_KEY), so this needs
no key juggling. `permission_mode="bypassPermissions"` is required or WebSearch waits on an
approval prompt and hangs; it is safe because `allowed_tools=["WebSearch"]` exposes only that
one tool.
"""

import asyncio

from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

from adaptive_academy.llm.agent_sdk_client import record_sdk_result
from adaptive_academy.llm.anthropic_researcher import parse_sources_json
from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.researcher_types import RawSource, SearchBrief
from adaptive_academy.llm.types import AgentSDKError
from adaptive_academy.prompts import RESEARCH_SEARCH


class AgentSDKResearcherClient:
    """One fan-out subagent: a single Agent SDK turn with WebSearch -> RawSource list."""

    def __init__(self, role: str = "reasoning", max_turns: int = 8):
        self._role = role
        self._model = get_model(role)
        self._max_turns = max_turns

    async def _run(self, web_query: str) -> str:
        text = ""
        async for msg in query(
            prompt=web_query,
            options=ClaudeAgentOptions(
                model=self._model, system_prompt=RESEARCH_SEARCH, allowed_tools=["WebSearch"],
                max_turns=self._max_turns, setting_sources=[],
                permission_mode="bypassPermissions"),
        ):
            if isinstance(msg, ResultMessage):
                record_sdk_result(msg, model=self._model, role=self._role,
                                  operation="research_search")
                if getattr(msg, "is_error", False):
                    raise AgentSDKError(getattr(msg, "result", "") or "agent SDK web-search error")
                text = getattr(msg, "result", "") or ""
        return text

    def search(self, brief: SearchBrief) -> list[RawSource]:
        sources = parse_sources_json(asyncio.run(self._run(brief.query)))
        for s in sources:
            s.angle = brief.angle
        return sources
