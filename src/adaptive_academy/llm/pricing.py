"""Per-model API list prices, so each recorded call can carry a dollar figure.

Source: https://platform.claude.com/docs/en/about-claude/pricing (read 2026-10-19).
Only prices verified on that page are listed. A model missing here still has its tokens
recorded; its cost is stored as NULL and the Usage page says "price unknown" — never a
guessed number. Update this table when Anthropic changes a price or a new default model
ships.

All rates are USD per million tokens. Cache writes are the 5-minute rate (1.25x input) unless
the response breaks out 1-hour writes (2x input). Web search is billed per search on top of
tokens ($10 per 1,000).
"""

import re
from dataclasses import dataclass

PRICING_SOURCE_URL = "https://platform.claude.com/docs/en/about-claude/pricing"
PRICING_READ_ON = "2026-10-19"

WEB_SEARCH_USD_PER_SEARCH = 10.0 / 1000


@dataclass(frozen=True)
class Rates:
    input: float
    output: float
    cache_write_5m: float
    cache_write_1h: float
    cache_read: float


@dataclass(frozen=True)
class ModelPricing:
    base: Rates
    # Claude Haiku 5.5 is priced by prompt length: a prompt (input + cache reads + cache
    # writes) over the threshold pays the long-context rates on the whole request.
    long_prompt: Rates | None = None
    long_prompt_threshold: int | None = None


PRICES: dict[str, ModelPricing] = {
    "claude-sonnet-5-5": ModelPricing(Rates(2.00, 10.00, 2.50, 4.00, 0.10)),
    "claude-sonnet-4-6": ModelPricing(Rates(3.00, 15.00, 3.75, 6.00, 0.30)),
    "claude-haiku-5-5": ModelPricing(
        Rates(0.10, 0.50, 0.125, 0.20, 0.01),
        long_prompt=Rates(0.50, 2.50, 0.625, 1.00, 0.05),
        long_prompt_threshold=100_000,
    ),
    "claude-haiku-4-5": ModelPricing(Rates(1.00, 5.00, 1.25, 2.00, 0.10)),
    # The likeliest overrides, so a daily limit doesn't refuse them as unpriced.
    "claude-opus-5-5": ModelPricing(Rates(4.00, 20.00, 5.00, 8.00, 0.20)),
    "claude-fable-5-1": ModelPricing(Rates(10.00, 50.00, 12.50, 20.00, 0.25)),
}

_DATED_SNAPSHOT = re.compile(r"-\d{8}$")


def price_for(model: str) -> ModelPricing | None:
    """The price entry for a model id; dated snapshots (…-20251001) fall back to the alias."""
    if not model:
        return None
    return PRICES.get(model) or PRICES.get(_DATED_SNAPSHOT.sub("", model))


def cost_usd(
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_input_tokens: int = 0,
    cache_read_input_tokens: int = 0,
    web_search_requests: int = 0,
    cache_creation_1h_input_tokens: int = 0,
) -> float | None:
    """Dollar cost of one call at list price, or None when the model's price is unknown.

    `cache_creation_input_tokens` is the total written to cache; the part of it written with
    a 1-hour TTL (when the response reports it) is priced at the 1-hour rate.
    """
    entry = price_for(model)
    if entry is None:
        return None
    rates = entry.base
    prompt = input_tokens + cache_creation_input_tokens + cache_read_input_tokens
    if (entry.long_prompt is not None and entry.long_prompt_threshold is not None
            and prompt > entry.long_prompt_threshold):
        rates = entry.long_prompt
    one_hour = min(max(cache_creation_1h_input_tokens, 0), cache_creation_input_tokens)
    five_min = cache_creation_input_tokens - one_hour
    per_token = (
        input_tokens * rates.input
        + output_tokens * rates.output
        + five_min * rates.cache_write_5m
        + one_hour * rates.cache_write_1h
        + cache_read_input_tokens * rates.cache_read
    ) / 1_000_000
    return per_token + web_search_requests * WEB_SEARCH_USD_PER_SEARCH
