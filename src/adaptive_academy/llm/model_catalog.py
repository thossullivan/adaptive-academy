"""What each model family supports, so per-model differences live in data, not scattered ifs.

The app's request shapes were built for Claude: strict tool use for structured output, the
Anthropic `web_search_20250305` server tool for research (with `pause_turn` continuations),
and thinking blocks passed back unchanged in a tool loop. Through OpenRouter's Messages
endpoint any model can be configured, and OpenRouter converts the request for it, but these
three features are only known to hold for Claude. So:

- `anthropic` (Claude: `claude-…` ids on the Anthropic API, `anthropic/claude-…` slugs and
  `~anthropic/…` aliases on OpenRouter): full support.
- `anthropic-legacy` (Claude older than 4.5, e.g. claude-3-5-sonnet, claude-sonnet-4): the
  same, except strict tool use, which those models don't support. Their structured output is
  sent without `strict`, as for an experimental model, with the same one corrective retry.
- everything else: allowed, but marked experimental. Its structured-output tool is sent
  without `strict` (the schema still shapes the answer, and a prose answer still gets the one
  corrective retry), research uses OpenRouter's own `openrouter:web_search` server tool, and
  thinking blocks from its responses are not replayed.

Add a family here (with what a live check showed) rather than branching on model names in a
client. `experimental` is the one source for the "Experimental" label in the UI.
"""

import re
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
    "anthropic-legacy": ModelCapabilities(
        family="anthropic-legacy",
        strict_tools=False,
        anthropic_web_search=True,
        thinking_replay=True,
        experimental=False,
    ),
}

# Strict tool use arrived with the Claude 4.5 generation.
STRICT_TOOLS_SINCE = (4, 5)
_DATE_SUFFIX = re.compile(r"-\d{8}$")

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


def claude_version(name: str) -> tuple[int, int] | None:
    """(major, minor) from a Claude model name, e.g. claude-sonnet-4-6 → (4, 6),
    claude-3-5-sonnet-20241022 → (3, 5), claude-sonnet-5.5 → (5, 5); None when the name
    carries no version (an alias such as claude-sonnet-latest)."""
    parts = _DATE_SUFFIX.sub("", name.split(":", 1)[0].replace(".", "-")).split("-")
    for i, part in enumerate(parts):
        if part.isdigit() and len(part) <= 2:
            nxt = parts[i + 1] if i + 1 < len(parts) else ""
            minor = int(nxt) if nxt.isdigit() and len(nxt) <= 2 else 0
            return int(part), minor
    return None


def family_of(model: str) -> str:
    """The family key for a model id: a direct `claude-…` id, or an OpenRouter
    `vendor/model[:variant]` slug (a leading `~` marks an OpenRouter alias)."""
    name = (model or "").strip().lower().lstrip("~")
    vendor, _, rest = name.rpartition("/") if "/" in name else ("", "", name)
    if vendor not in ("", "anthropic") or not rest.startswith("claude"):
        return OTHER.family
    version = claude_version(rest)
    if version is not None and version < STRICT_TOOLS_SINCE:
        return "anthropic-legacy"
    return "anthropic"


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


def is_openrouter_slug(model: str) -> bool:
    """OpenRouter model ids are `vendor/model` (optionally `~vendor/model` or with a
    `:variant` suffix)."""
    vendor, _, rest = (model or "").strip().lstrip("~").partition("/")
    return bool(vendor) and bool(rest)


def experimental_models() -> list[str]:
    """The configured models (any role) that are experimental, deduplicated, in role order."""
    from adaptive_academy.llm.registry import resolved_models

    out: list[str] = []
    for model in resolved_models().values():
        if is_experimental(model) and model not in out:
            out.append(model)
    return out
