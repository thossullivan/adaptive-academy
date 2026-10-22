import json
import logging

from anthropic import Anthropic

from adaptive_academy.jsonout import extract_json
from adaptive_academy.llm.anthropic_client import (
    EPHEMERAL,
    cached_system,
    content_block_to_param,
)
from adaptive_academy.llm.keys import require_anthropic_api_key
from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.researcher_types import RawSource, SearchBrief
from adaptive_academy.llm.usage import BACKEND_ANTHROPIC, check_budget, record_usage
from adaptive_academy.prompts import RESEARCH_SEARCH

logger = logging.getLogger(__name__)

# A long server-side search turn can stop with stop_reason "pause_turn"; it is continued by
# re-sending the paused content. Bounded like any retry loop: at most this many extra calls.
MAX_PAUSE_CONTINUATIONS = 3


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
    """Real fan-out subagent: one Anthropic Messages call with the web_search tool."""

    def __init__(self, role: str = "reasoning", max_tokens: int = 16_000, max_searches: int = 5):
        # 16k, not 2048 (or 8192): a web_search turn spends output tokens on the search then
        # the source JSON, and on models that think by default (Sonnet/Haiku 5.5) max_tokens
        # also covers the thinking. At 2048 it hit max_tokens and truncated mid-JSON, so every
        # angle silently parsed to 0 sources. Billing is per output token actually generated,
        # so the headroom is free. Stays under the SDK's non-streaming limit (~21.3k).
        # Known limit: the SDK's own retries (after a read timeout or dropped connection)
        # happen inside messages.create and their usage is never reported back, so a
        # retried search is recorded (and counted against the daily limit) only once.
        self._client = Anthropic(api_key=require_anthropic_api_key(), max_retries=2)
        self._role = role
        self._model = get_model(role)
        self._max_tokens = max_tokens
        self._max_searches = max_searches

    def search(self, brief: SearchBrief) -> list[RawSource]:
        tools = [{"type": "web_search_20250305", "name": "web_search",
                  "max_uses": self._max_searches}]
        user = {"role": "user", "content": brief.query}
        paused: list[dict] = []  # the still-open assistant turn, across pause_turn stops
        texts: list[str] = []
        for _ in range(1 + MAX_PAUSE_CONTINUATIONS):
            messages = [user, {"role": "assistant", "content": paused}] if paused else [user]
            check_budget(self._model)
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=self._max_tokens,
                system=cached_system(RESEARCH_SEARCH),
                tools=tools,  # same tools: a paused turn may end on a not-yet-run search
                messages=messages,
                # Automatic caching as well: a pause_turn continuation re-sends the search
                # results (large), and reads them from cache instead of paying full price.
                cache_control=EPHEMERAL,
            )
            # usage.server_tool_use.web_search_requests is billed per search on top of
            # tokens; every continuation is its own billed call, so its own row.
            record_usage(backend=BACKEND_ANTHROPIC, model=self._model, role=self._role,
                         operation="research_search", usage=getattr(resp, "usage", None))
            # By type: thinking, server_tool_use and web_search_tool_result blocks skipped.
            texts.append(
                "".join(b.text for b in resp.content if getattr(b, "type", None) == "text"))
            if getattr(resp, "stop_reason", None) != "pause_turn":
                break
            # The server-side search loop paused a long turn: send the paused content back
            # unchanged so the model continues the same turn.
            paused = [*paused, *(content_block_to_param(b) for b in resp.content)]
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
