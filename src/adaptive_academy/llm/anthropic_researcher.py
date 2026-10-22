import json
import logging

import httpx
from anthropic import Anthropic

from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.anthropic_client import (
    EPHEMERAL,
    cached_system,
    content_block_to_param,
    sdk_client_kwargs,
)
from adaptive_academy.llm.backends import api_backend, request_extra_body
from adaptive_academy.llm.model_catalog import replayable, web_search_limits, web_search_tool
from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.researcher_types import RawSource, SearchBrief
from adaptive_academy.llm.today import today_line
from adaptive_academy.llm.usage import check_budget, record_usage
from adaptive_academy.prompts import RESEARCH_SEARCH

logger = logging.getLogger(__name__)

# A long server-side search turn can stop with stop_reason "pause_turn"; it is continued by
# re-sending the paused content. Bounded like any retry loop: at most this many extra calls.
MAX_PAUSE_CONTINUATIONS = 3


def _searches(resp) -> int:
    """usage.server_tool_use.web_search_requests of a response, 0 when not reported."""
    value = getattr(getattr(getattr(resp, "usage", None), "server_tool_use", None),
                    "web_search_requests", None)
    return value if isinstance(value, int) and value > 0 else 0


def parse_sources_json(text: str) -> list[RawSource]:
    """Extract a RawSource list from model text. Returns [] on any parse failure."""
    try:
        data = json.loads(extract_json(text))
    except (json.JSONDecodeError, ValueError):
        return []
    out: list[RawSource] = []
    for d in data if isinstance(data, list) else []:
        if not isinstance(d, dict) or not d.get("url"):
            continue
        out.append(
            RawSource(
                title=str(d.get("title", d.get("url"))),
                url=str(d["url"]),
                tier=int(d.get("tier", 3)),
                summary=str(d.get("summary", "")),
                why=str(d.get("why", "")),
                relevance=float(d.get("relevance", 0.0)),
            )
        )
    return out


class AnthropicResearcherClient:
    """Real fan-out subagent: one Messages call with a server-side web search tool.

    Anthropic's `web_search_20250305` for Claude (directly or through OpenRouter), OpenRouter's
    `openrouter:web_search` for other models (llm/model_catalog.py).
    """

    def __init__(
        self,
        role: str = "reasoning",
        max_tokens: int = 16_000,
        max_searches: int = 5,
        *,
        http_client: httpx.Client | None = None,
    ):
        # 16k, not 2048 (or 8192): a web_search turn spends output tokens on the search then
        # the source JSON, and on models that think by default (Sonnet/Haiku 5.5) max_tokens
        # also covers the thinking. At 2048 it hit max_tokens and truncated mid-JSON, so every
        # angle silently parsed to 0 sources. Billing is per output token actually generated,
        # so the headroom is free. Stays under the SDK's non-streaming limit (~21.3k).
        # Known limit: the SDK's own retries (after a read timeout or dropped connection)
        # happen inside messages.create and their usage is never reported back, so a
        # retried search is recorded (and counted against the daily limit) only once.
        # `http_client`: test seam only, as on AnthropicLLMClient.
        self._backend = api_backend()
        self._client = Anthropic(**sdk_client_kwargs(self._backend), max_retries=2,
                                 http_client=http_client)
        self._role = role
        self._model = get_model(role)
        self._max_tokens = max_tokens
        self._max_searches = max_searches
        # Fixed for this client's life (built per request): a pause_turn continuation echoes
        # thinking blocks bound to the system prompt, so the date must not change mid-loop.
        self._today = today_line()

    def search(self, brief: SearchBrief) -> list[RawSource]:
        user = {"role": "user", "content": brief.query}
        paused: list[dict] = []  # the still-open assistant turn, across pause_turn stops
        texts: list[str] = []
        searched = 0  # web_search_requests reported so far for this angle
        for _ in range(1 + MAX_PAUSE_CONTINUATIONS):
            # max_uses (and OpenRouter's loop stop) count per request, and a continuation is
            # a new request, so it carries only what is left of the angle's cap.
            budget = self._max_searches - searched
            tools = [web_search_tool(self._model, budget)]
            limits = web_search_limits(self._model, budget)
            messages = [user, {"role": "assistant", "content": paused}] if paused else [user]
            check_budget(self._model, reports_cost=self._backend.reports_cost,
                         backend=self._backend.name)
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=cached_system(RESEARCH_SEARCH, self._today),
                # Same tool on a continuation (only max_uses lowered): a paused turn may end
                # on a not-yet-run search, and a continuation without its tool is rejected.
                tools=tools,
                messages=messages,
                # Automatic caching as well: a pause_turn continuation re-sends the search
                # results (large), and reads them from cache instead of paying full price.
                cache_control=EPHEMERAL,
                **request_extra_body(self._backend, limits),
            )
            # usage.server_tool_use.web_search_requests is billed per search on top of
            # tokens; every continuation is its own billed call, so its own row.
            record_usage(backend=self._backend.name, model=self._model, role=self._role,
                         operation="research_search", usage=getattr(resp, "usage", None))
            # By type: thinking, server_tool_use and web_search_tool_result blocks skipped.
            texts.append(
                "".join(b.text for b in resp.content if getattr(b, "type", None) == "text"))
            if getattr(resp, "stop_reason", None) != "pause_turn":
                break
            searched += _searches(resp)
            if searched >= self._max_searches:
                # The cap is spent. A continuation would run the paused turn's pending
                # search at once and needs the search tool kept (dropping it is a 400), so
                # the turn ends here, like the max-continuations path below.
                logger.warning("research search for angle %r used its %d searches and is "
                               "still paused; using the text so far", brief.angle,
                               self._max_searches)
                break
            # The server-side search loop paused a long turn: send the paused content back
            # unchanged so the model continues the same turn.
            paused = [*paused, *replayable(
                self._model, [content_block_to_param(b) for b in resp.content])]
        else:
            logger.warning("research search for angle %r still paused after %d "
                           "continuations; using the text so far", brief.angle,
                           MAX_PAUSE_CONTINUATIONS)
        # The source list is normally in the final turn's text; fall back to the whole turn
        # in case it was written before a pause.
        sources = parse_sources_json(texts[-1]) or parse_sources_json("\n".join(texts))
        for s in sources:
            s.angle = brief.angle
        return sources
