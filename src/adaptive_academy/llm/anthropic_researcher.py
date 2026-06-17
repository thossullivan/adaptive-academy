import json
import os

from anthropic import Anthropic

from adaptive_academy.llm.registry import get_model
from adaptive_academy.llm.researcher_types import RawSource, SearchBrief
from adaptive_academy.prompts import RESEARCH_SEARCH


def parse_sources_json(text: str) -> list[RawSource]:
    """Extract a RawSource list from model text. Returns [] on any parse failure."""
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```", 2)[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[len("json"):]
        cleaned = cleaned.strip()
    # Trim to the outermost JSON array if surrounded by stray text.
    start, end = cleaned.find("["), cleaned.rfind("]")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    try:
        data = json.loads(cleaned)
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

    def __init__(self, role: str = "reasoning", max_tokens: int = 8192, max_searches: int = 5):
        # 8192, not 2048: a web_search turn spends output tokens on the search then the
        # source JSON; at 2048 it hit max_tokens and truncated mid-JSON, so every angle
        # silently parsed to 0 sources. Billing is per output token, so the headroom is free.
        self._client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"], max_retries=2)
        self._model = get_model(role)
        self._max_tokens = max_tokens
        self._max_searches = max_searches

    def search(self, brief: SearchBrief) -> list[RawSource]:
        resp = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=RESEARCH_SEARCH,
            tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": self._max_searches}],
            messages=[{"role": "user", "content": brief.query}],
        )
        text = "".join(b.text for b in resp.content if getattr(b, "type", None) == "text")
        sources = parse_sources_json(text)
        for s in sources:
            s.angle = brief.angle
        return sources
