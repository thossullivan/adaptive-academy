"""What each model family supports, so per-model differences live in data, not scattered ifs.

The app's request shapes were built for Claude: strict tool use for structured output, the
Anthropic `web_search_20250305` server tool for research (with `pause_turn` continuations),
and thinking blocks passed back unchanged in a tool loop. Through OpenRouter's Messages
endpoint any model can be configured, and OpenRouter converts the request for it, but these
three features are only known to hold for Claude. So:

- `anthropic` (Claude: `claude-…` ids on the Anthropic API, `anthropic/claude-…` slugs on
  OpenRouter): full support.
- everything else: allowed, but marked experimental. Its structured-output tool is sent
  without `strict` (the schema still shapes the answer, and a prose answer still gets the one
  corrective retry), research uses OpenRouter's own `openrouter:web_search` server tool, and
  thinking blocks from its responses are not replayed.

Add a family here (with what a live check showed) rather than branching on model names in a
client. `experimental` is the one source for the "Experimental" label in the UI.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ModelCapabilities:
    family: str
    # `strict: true` on a tool guarantees schema-valid input.
    strict_tools: bool
    # Anthropic's `web_search_20250305` server tool (and its pause_turn continuations).
    anthropic_web_search: bool
    # Thinking blocks must (and can) be passed back unchanged within a turn's tool loop.
    thinking_replay: bool
    # Not an Anthropic Claude model: works through OpenRouter's conversion, unverified here.
    experimental: bool


FAMILIES: dict[str, ModelCapabilities] = {
    "anthropic": ModelCapabilities(
        family="anthropic",
        strict_tools=True,
        anthropic_web_search=True,
        thinking_replay=True,
        experimental=False,
    ),
}

OTHER = ModelCapabilities(
    family="other",
    strict_tools=False,
    anthropic_web_search=False,
    thinking_replay=False,
    experimental=True,
)

# Request shapes. The Anthropic tool is the one the API-key path has always used. OpenRouter's
# server tool: `{"type": "openrouter:web_search", "parameters": {...}}`, where `max_uses` is
# "Maximum number of searches the model may perform in a single request" (OpenRouter docs,
# guides/features/server-tools/web-search, read 2026-10-22).
ANTHROPIC_WEB_SEARCH_TYPE = "web_search_20250305"
OPENROUTER_WEB_SEARCH_TYPE = "openrouter:web_search"

# Content block types that carry the model's reasoning.
THINKING_BLOCK_TYPES = frozenset({"thinking", "redacted_thinking"})


def family_of(model: str) -> str:
    """The family key for a model id: a direct `claude-…` id or an OpenRouter
    `vendor/model[:variant]` slug whose vendor is a known family."""
    name = (model or "").strip().lower()
    if "/" in name:
        vendor = name.split("/", 1)[0]
        return vendor if vendor in FAMILIES else OTHER.family
    if name.startswith("claude-"):
        return "anthropic"
    return OTHER.family


def capabilities(model: str) -> ModelCapabilities:
    return FAMILIES.get(family_of(model), OTHER)


def is_experimental(model: str) -> bool:
    return capabilities(model).experimental


def web_search_tool(model: str, max_uses: int) -> dict[str, Any]:
    """The research client's web search server tool for this model."""
    if capabilities(model).anthropic_web_search:
        return {"type": ANTHROPIC_WEB_SEARCH_TYPE, "name": "web_search", "max_uses": max_uses}
    return {"type": OPENROUTER_WEB_SEARCH_TYPE, "parameters": {"max_uses": max_uses}}


def replayable(model: str, blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Response blocks as they may be sent back: unchanged for a model that replays thinking,
    without its thinking blocks otherwise."""
    if capabilities(model).thinking_replay:
        return blocks
    return [b for b in blocks if b.get("type") not in THINKING_BLOCK_TYPES]


def experimental_models() -> list[str]:
    """The configured models (any role) that are experimental, deduplicated, in role order."""
    from adaptive_academy.llm.registry import resolved_models

    out: list[str] = []
    for model in resolved_models().values():
        if is_experimental(model) and model not in out:
            out.append(model)
    return out
