"""Per-model pricing: verified prices only, cache + web-search math, unknown → None."""

import pytest

from adaptive_academy.llm import pricing


def test_sonnet_4_6_input_output_cache_and_search_math():
    cost = pricing.cost_usd(
        "claude-sonnet-4-6",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
        cache_creation_input_tokens=1_000_000,
        cache_read_input_tokens=1_000_000,
        web_search_requests=3,
    )
    # $3 in + $15 out + $3.75 5m cache write + $0.30 cache read + 3 x $0.01 search
    assert cost == pytest.approx(3 + 15 + 3.75 + 0.30 + 0.03)


def test_one_hour_cache_writes_are_priced_at_the_one_hour_rate():
    cost = pricing.cost_usd(
        "claude-haiku-4-5",
        cache_creation_input_tokens=2_000_000,
        cache_creation_1h_input_tokens=1_000_000,
    )
    # 1M at the 5m write rate ($1.25) + 1M at the 1h write rate ($2)
    assert cost == pytest.approx(1.25 + 2.0)


@pytest.mark.parametrize(
    ("model", "inp", "out", "read"),
    [
        ("claude-sonnet-5-5", 2.0, 10.0, 0.10),
        ("claude-sonnet-4-6", 3.0, 15.0, 0.30),
        ("claude-haiku-4-5", 1.0, 5.0, 0.10),
        ("claude-haiku-5-5", 0.10, 0.50, 0.01),
    ],
)
def test_per_million_rates(model, inp, out, read):
    # 50k-token prompts stay under Haiku 5.5's 100k long-prompt threshold.
    assert pricing.cost_usd(model, input_tokens=50_000) == pytest.approx(inp / 20)
    assert pricing.cost_usd(model, output_tokens=1_000_000) == pytest.approx(out)
    assert pricing.cost_usd(model, cache_read_input_tokens=50_000) == pytest.approx(read / 20)


def test_haiku_5_5_long_prompt_pays_the_higher_tier_on_every_token():
    # Prompt length counts input + cache reads + cache writes; over 100k → the whole
    # request is priced at the long-context rates.
    short = pricing.cost_usd("claude-haiku-5-5", input_tokens=100_000, output_tokens=1_000)
    assert short == pytest.approx(100_000 * 0.10 / 1e6 + 1_000 * 0.50 / 1e6)
    long = pricing.cost_usd(
        "claude-haiku-5-5",
        input_tokens=60_000,
        cache_read_input_tokens=50_000,
        output_tokens=1_000,
    )
    assert long == pytest.approx(
        60_000 * 0.50 / 1e6 + 50_000 * 0.05 / 1e6 + 1_000 * 2.50 / 1e6
    )


def test_dated_snapshot_ids_resolve_to_their_alias_price():
    assert pricing.cost_usd("claude-haiku-4-5-20251001", input_tokens=1_000_000) == (
        pytest.approx(1.0)
    )


@pytest.mark.parametrize("model", ["claude-imaginary-9", "", "gpt-5"])
def test_unknown_model_has_no_price(model):
    assert pricing.cost_usd(model, input_tokens=10, output_tokens=10) is None
    assert pricing.price_for(model) is None


def test_zero_usage_on_a_known_model_costs_zero_not_none():
    assert pricing.cost_usd("claude-sonnet-4-6") == 0.0
