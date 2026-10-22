"""What the model calls cost: recorded tokens, dollars, and the daily limit.

Dollars are what the service reported charging where it reports it (OpenRouter), else the
list price (llm/pricing.py). See llm/usage.py.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlmodel import Session

from adaptive_academy.api.deps import get_session
from adaptive_academy.llm import pricing
from adaptive_academy.llm.backends import current_backend_name
from adaptive_academy.llm.usage import usage_summary

router = APIRouter(prefix="/api/usage", tags=["usage"])


class UsageTotalsOut(BaseModel):
    calls: int
    cost_usd: float  # all recorded cost, incl. the Agent SDK's own estimate
    api_cost_usd: float  # API-key (backend "anthropic" or "openrouter") spend only
    unpriced_calls: int  # calls with neither a reported cost nor a known price
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int
    cache_read_input_tokens: int
    web_search_requests: int


class UsageWindowsOut(BaseModel):
    today: UsageTotalsOut
    last_7_days: UsageTotalsOut
    last_30_days: UsageTotalsOut
    all_time: UsageTotalsOut


class FeatureUsageOut(UsageTotalsOut):
    feature: str | None
    # Input tokens read from the prompt cache, as a share of all input tokens (0..1); None
    # when the feature sent none.
    cache_read_share: float | None


class ModelUsageOut(UsageTotalsOut):
    model: str
    # Not an Anthropic Claude model (llm/model_catalog.py): shown with an "Experimental" label.
    experimental: bool = False


class BudgetOut(BaseModel):
    limit_usd: float | None
    spent_today_usd: float
    remaining_usd: float | None
    exceeded: bool


class UsageOut(BaseModel):
    backend: Literal["anthropic", "agent_sdk", "openrouter"]
    totals: UsageWindowsOut
    by_feature: list[FeatureUsageOut]  # last 30 days
    by_model: list[ModelUsageOut]  # last 30 days
    budget: BudgetOut
    priced_models: list[str]
    pricing_source: str
    pricing_as_of: str


@router.get("", response_model=UsageOut)
def get_usage(session: Session = Depends(get_session)) -> UsageOut:
    summary = usage_summary(session)
    return UsageOut(
        backend=current_backend_name(),
        priced_models=sorted(pricing.PRICES),
        pricing_source=pricing.PRICING_SOURCE_URL,
        pricing_as_of=pricing.PRICING_READ_ON,
        **summary,
    )
