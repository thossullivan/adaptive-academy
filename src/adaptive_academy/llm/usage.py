"""Token/cost accounting for every real model call, and the daily spending limit.

Recording: each LLM client calls `record_usage(...)` right after its model call returns. The
row goes through the one bounded trace writer (engine/trace_writer.py), so it is written in
its own short session off the request thread — never inside the caller's transaction, never
waiting on SQLite's write lock — and any failure is logged and swallowed: usage accounting
must never break a call that already succeeded (and was already billed).

Feature attribution: a contextvar holds a short label for the API route that triggered the
call (set by a FastAPI dependency in api/app.py, from the matched route template), so engine
code needs no extra parameters. Non-request callers (CLI, scripts) record feature=NULL.

Cost: each row keeps the list-price cost (llm/pricing.py, `cost_usd`; OpenRouter slugs for
Claude models use the Anthropic price) and, where the service reports one, what it actually
charged (`reported_cost_usd`: OpenRouter's `usage.cost`, which includes its fees; on a BYOK
request, `usage.cost` plus `cost_details.upstream_inference_cost`, what the provider billed
your own key). The reported cost wins wherever cost is summed (`effective_cost`): the Usage
page and the daily limit. A row with neither is a call whose spend is unknown.

Budget: `check_budget(model)` runs before every API-key call (backend "anthropic" or
"openrouter"). When AA_DAILY_BUDGET_USD is set and today's recorded API-key spend already
meets or exceeds it, it raises BudgetExceededError (→ HTTP 429). "Today" is the server's local
calendar day (UTC in the Docker image unless TZ is set). A single call can overshoot the limit
— the check runs before the call, and the call's cost is only known after it. On a backend
that doesn't report cost (Anthropic), a call on a model with no known price would be recorded
at $0 and never trip the limit, so while a limit is set such a call is refused up front
(UnpricedModelError, also → 429). On OpenRouter calls report their cost, so a model with no
list price may run under a limit, until a response arrives without a cost: then its next call
is refused (UnreportedCostError). If today's spend can't be read while a limit is set, the call
is refused too (BudgetUnreadableError): the limit fails closed. Agent SDK calls are billed to
the Claude subscription, not a key, so they are recorded but never blocked.
"""

from __future__ import annotations

import contextvars
import logging
import math
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from adaptive_academy.engine.trace_writer import TRACE_WRITER
from adaptive_academy.llm import model_catalog, pricing
from adaptive_academy.llm.backends import (
    BACKEND_AGENT_SDK,
    BACKEND_ANTHROPIC,
    BACKEND_OPENROUTER,
    KEY_BILLED_BACKENDS,
    api_backend,
)
from adaptive_academy.models import LLMUsage
from adaptive_academy.settings import settings

logger = logging.getLogger(__name__)

# Re-exported for the clients that import them from here.
__all__ = ["BACKEND_AGENT_SDK", "BACKEND_ANTHROPIC", "BACKEND_OPENROUTER"]

# What a row cost: the service's reported charge when there is one, else the list price.
effective_cost = func.coalesce(LLMUsage.reported_cost_usd, LLMUsage.cost_usd)


class BudgetExceededError(RuntimeError):
    """Today's API-key spend already meets the AA_DAILY_BUDGET_USD limit (→ HTTP 429)."""

    def __init__(self, spent_usd: float, limit_usd: float):
        self.spent_usd = spent_usd
        self.limit_usd = limit_usd
        super().__init__(
            f"Daily spending limit reached: ${spent_usd:.2f} spent today of a "
            f"${limit_usd:.2f} limit (AA_DAILY_BUDGET_USD). Raise or unset "
            "AA_DAILY_BUDGET_USD in .env and restart the API, or wait until tomorrow "
            "(the server's local day). See the Usage page for where it went."
        )


class UnpricedModelError(BudgetExceededError):
    """A daily limit is set but the call's model has no known price (→ HTTP 429).

    Its spend would be recorded as unknown ($0 to the budget), so the limit could not cap it.
    A BudgetExceededError subclass so every path that stops on the budget (the 429 handler,
    the research fan-out) stops on this too.
    """

    def __init__(self, model: str, limit_usd: float):
        self.model = model
        self.spent_usd = None
        self.limit_usd = limit_usd
        RuntimeError.__init__(self, unpriced_model_message(model))


class UnreportedCostError(BudgetExceededError):
    """A daily limit is set, the model has no list price, and the backend didn't report the
    cost of this model's last call today, so its spend can't be counted (→ HTTP 429)."""

    def __init__(self, model: str, limit_usd: float, provider: str = "OpenRouter"):
        self.model = model
        self.spent_usd = None
        self.limit_usd = limit_usd
        RuntimeError.__init__(self, unreported_cost_message(model, provider))


def unreported_cost_message(model: str, provider: str = "OpenRouter") -> str:
    return (
        f"A daily spending limit is set (AA_DAILY_BUDGET_USD) but {provider} did not report "
        f"the cost of today's last call on '{model}', and this app has no price for it, so its "
        "spend can't be capped and its calls are refused. This clears at midnight (the "
        "server's local day), or once a call on it made with AA_DAILY_BUDGET_USD unset "
        "reports its cost. To use it now, unset AA_DAILY_BUDGET_USD or switch to a Claude "
        "model (AA_MODEL_REASONING / AA_MODEL_COPY), then restart the API."
    )


class BudgetUnreadableError(BudgetExceededError):
    """A daily limit is set but today's recorded spend can't be read (→ HTTP 429): refuse
    rather than risk running past the limit."""

    def __init__(self, limit_usd: float):
        self.spent_usd = None
        self.limit_usd = limit_usd
        RuntimeError.__init__(
            self,
            "A daily spending limit is set (AA_DAILY_BUDGET_USD) but today's spend could not "
            "be read, so the call was refused rather than risk going past the limit. Check "
            "the API log. If the database is behind this version of the app, run "
            "`uv run alembic upgrade head` (the container does this when it starts) and "
            "restart the API.")


def unpriced_model_message(model: str) -> str:
    return (
        f"A daily spending limit is set (AA_DAILY_BUDGET_USD) but the model '{model}' has no "
        "known price, so its spend can't be capped. Use a priced model "
        "(AA_MODEL_REASONING / AA_MODEL_COPY) or unset AA_DAILY_BUDGET_USD, then restart "
        "the API."
    )


# --- where usage rows go --------------------------------------------------------------

_UNSET: Any = object()
_bind_override: Any = _UNSET


def set_usage_bind(bind: Engine | None) -> None:
    """Point recording at `bind` (tests); None disables recording and the budget read."""
    global _bind_override
    _bind_override = bind


def reset_usage_bind() -> None:
    global _bind_override
    _bind_override = _UNSET


def get_usage_bind() -> Engine | None:
    if _bind_override is _UNSET:
        from adaptive_academy.db import engine

        return engine
    return _bind_override


# --- feature attribution --------------------------------------------------------------

_current_feature: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "aa_llm_feature", default=None
)

# Route segment → feature label. Scanned from the end of the route template, so the most
# specific segment wins ("/api/programs/{id}/research" → research, not programs).
_FEATURE_SEGMENTS = {
    "conversations": "tutor",
    "assess": "assess",
    "remediate": "remediate",
    "research": "research",
    "curriculum": "curriculum",
    "anchors": "anchors",
    "productive_failure": "productive_failure",
    "teach": "teach",
    "story": "story",
    "sources": "sources",
    "roleplay": "roleplay",
    "paper-probe": "paper_probe",
    "revise": "revision",
    "revision": "revision",
    "changes": "revision",
    "scout": "scout",
    "decay": "decay",
    "retention": "retention",
    "deliverables": "deliverables",
    "memory": "memory",
    "vault": "vault",
    "items": "items",
    "programs": "programs",
    "topics": "topics",
    "concepts": "concepts",
}


def feature_from_route(path: str | None) -> str | None:
    """Short feature label for a route template, e.g. '/api/topics/{topic_id}/research'."""
    if not path:
        return None
    literals = [s for s in path.split("/") if s and not s.startswith("{")]
    if literals and literals[0] == "api":
        literals = literals[1:]
    for segment in reversed(literals):
        if segment in _FEATURE_SEGMENTS:
            return _FEATURE_SEGMENTS[segment]
    return literals[-1] if literals else None


def current_feature() -> str | None:
    return _current_feature.get()


def set_feature(feature: str | None) -> contextvars.Token:
    return _current_feature.set(feature)


@contextmanager
def feature_context(feature: str | None) -> Iterator[None]:
    token = _current_feature.set(feature)
    try:
        yield
    finally:
        _current_feature.reset(token)


# --- recording ------------------------------------------------------------------------


def _field(obj: Any, name: str) -> Any:
    """Read `name` from an SDK object or a plain dict (the Agent SDK's usage is a dict)."""
    if obj is None:
        return None
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(int(value), 0)
    return 0


def _reported_cost(value: Any) -> float | None:
    """A charge the service reported (OpenRouter's usage.cost), or None if absent or not a
    usable dollar amount."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) and value >= 0 else None


def _reported_charge(usage: Any) -> float | None:
    """What the call cost per the service: `usage.cost`, plus, on a BYOK request,
    `cost_details.upstream_inference_cost` (OpenRouter's usage-accounting docs: `cost` is what
    OpenRouter charged the account, the upstream cost what the provider billed your own key;
    the docs don't state the sum, so it is our reading). A BYOK row without the upstream part
    reports None, so the list price stands in."""
    cost = _reported_cost(_field(usage, "cost"))
    if cost is None:
        return None
    if _field(usage, "is_byok") is True:
        upstream = _reported_cost(
            _field(_field(usage, "cost_details"), "upstream_inference_cost"))
        return None if upstream is None else cost + upstream
    return cost


def _build_row(
    *,
    backend: str,
    model: str,
    role: str,
    operation: str,
    usage: Any,
    total_cost_usd: Any = None,
) -> LLMUsage:
    input_tokens = _int(_field(usage, "input_tokens"))
    output_tokens = _int(_field(usage, "output_tokens"))
    cache_write = _int(_field(usage, "cache_creation_input_tokens"))
    cache_read = _int(_field(usage, "cache_read_input_tokens"))
    searches = _int(_field(_field(usage, "server_tool_use"), "web_search_requests"))
    if backend == BACKEND_AGENT_SDK:
        # The SDK prices its own run (all turns, any internal model calls); it is what the
        # subscription would have cost at list price, not money charged to the API key.
        cost = float(total_cost_usd) if isinstance(total_cost_usd, (int, float)) else None
    else:
        cost = pricing.cost_usd(
            model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_creation_input_tokens=cache_write,
            cache_read_input_tokens=cache_read,
            web_search_requests=searches,
            cache_creation_1h_input_tokens=_int(
                _field(_field(usage, "cache_creation"), "ephemeral_1h_input_tokens")
            ),
        )
    return LLMUsage(
        backend=backend,
        model=model or "",
        role=role or "",
        operation=operation,
        feature=current_feature(),
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_input_tokens=cache_write,
        cache_read_input_tokens=cache_read,
        web_search_requests=searches,
        cost_usd=cost,
        reported_cost_usd=_reported_charge(usage),
    )


def record_usage(
    *,
    backend: str,
    model: str,
    role: str,
    operation: str,
    usage: Any,
    total_cost_usd: Any = None,
) -> None:
    """Best-effort: queue one LLMUsage row. Never raises."""
    try:
        bind = get_usage_bind()
        if bind is None:
            return
        row = _build_row(backend=backend, model=model, role=role, operation=operation,
                         usage=usage, total_cost_usd=total_cost_usd)
        # One retry on a lock timeout: this row is what the daily limit counts.
        TRACE_WRITER.submit(bind, [row], retries=1)
    except Exception:  # noqa: BLE001 - accounting must never break a billed call
        logger.exception("usage recording failed for %s/%s; the call itself succeeded",
                         backend, operation)


# --- budget ---------------------------------------------------------------------------


def local_day_start(now: datetime | None = None) -> datetime:
    """Midnight of the server's local day containing `now`, as an aware UTC datetime."""
    local = now if now is not None else datetime.now().astimezone()
    if local.tzinfo is None:
        local = local.astimezone()
    midnight = local.replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight.astimezone(timezone.utc)


def _db_time(moment: datetime) -> datetime:
    # created_at is stored as naive UTC (SQLite drops the offset), so compare like with like.
    return moment.astimezone(timezone.utc).replace(tzinfo=None)


def _close_read_session(session: Session, bind: Engine) -> None:
    # The in-memory test engine (StaticPool) shares ONE connection with the caller's session;
    # closing a read session rolls that connection back and would discard the caller's
    # flushed rows. Commit instead (the same trade the trace writer's inline mode makes).
    if isinstance(bind.pool, StaticPool):
        session.commit()


def spent_today_usd(now: datetime | None = None) -> float:
    """Recorded API-key spend since local midnight (reported cost where the service reports
    one, else list price). Unknown-price calls count as $0."""
    bind = get_usage_bind()
    if bind is None:
        return 0.0
    start = _db_time(local_day_start(now))
    with Session(bind) as session:
        total = session.exec(
            select(func.coalesce(func.sum(effective_cost), 0.0)).where(
                LLMUsage.created_at >= start,
                LLMUsage.backend.in_(KEY_BILLED_BACKENDS),
            )
        ).one()
        _close_read_session(session, bind)
    return float(total or 0.0)


def last_call_unreported(model: str, backend: str, now: datetime | None = None) -> bool:
    """True when this model's most recent call on `backend` TODAY (the server's local day,
    like the limit) was recorded with neither a reported cost nor a list price: the service
    stopped reporting what it charged. Scoped to today because a refused call writes no row,
    so an unscoped lookup would block the model under a limit for good."""
    bind = get_usage_bind()
    if bind is None:
        return False
    start = _db_time(local_day_start(now))
    with Session(bind) as session:
        row = session.exec(
            select(LLMUsage.reported_cost_usd, LLMUsage.cost_usd)
            .where(LLMUsage.backend == backend, LLMUsage.model == model,
                   LLMUsage.created_at >= start)
            .order_by(LLMUsage.id.desc())
            .limit(1)
        ).first()
        _close_read_session(session, bind)
    return row is not None and row[0] is None and row[1] is None


def check_budget(model: str | None = None, *, reports_cost: bool = False,
                 backend: str = BACKEND_ANTHROPIC) -> None:
    """With AA_DAILY_BUDGET_USD set, refuse (a BudgetExceededError, → 429) a call whose spend
    can't be capped or that today's spend already rules out:

    - UnpricedModelError: `model` has no list price on a backend that doesn't report what
      it charged (`reports_cost` False, see llm/backends.py);
    - UnreportedCostError: no list price, and the reporting backend left this model's last
      call today without a cost (clears at local midnight);
    - BudgetUnreadableError: today's spend (or that last call) can't be read. Fails closed:
      with a limit set, an unreadable usage store must not mean unlimited spend;
    - BudgetExceededError: today's spend meets the limit.
    """
    limit = settings.daily_budget_usd
    if limit is None:
        return
    try:
        if model is not None and pricing.price_for(model) is None:
            if not reports_cost:
                raise UnpricedModelError(model, limit)
            if last_call_unreported(model, backend):
                raise UnreportedCostError(model, limit)
        spent = spent_today_usd()
    except BudgetExceededError:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.warning("daily budget check failed: could not read recorded usage; refusing "
                       "the call", exc_info=True)
        raise BudgetUnreadableError(limit) from exc
    if spent >= limit:
        raise BudgetExceededError(spent, limit)


def budget_warnings() -> list[str]:
    """Configuration problems with the daily limit, for GET /api/setup (empty when fine).

    A limit is set and a configured role's model has no known price: on a backend that
    doesn't report cost, every API-key call on that role will be refused; on one that does
    (OpenRouter), only once today's last call on that model came back without a cost (see
    check_budget), and the warning says how that clears.
    """
    if settings.daily_budget_usd is None:
        return []
    from adaptive_academy.llm.registry import MODEL_ENV_VARS, resolved_models

    backend = api_backend()
    by_model: dict[str, list[str]] = {}
    for role, model in resolved_models().items():
        if pricing.price_for(model) is None:
            by_model.setdefault(model, []).append(MODEL_ENV_VARS[role])
    if not backend.reports_cost:
        return [
            f"{unpriced_model_message(model)} Until then, calls on {' / '.join(env_vars)} "
            "are refused."
            for model, env_vars in by_model.items()
        ]
    warnings = []
    for model in by_model:
        try:
            blocked = last_call_unreported(model, backend.name)
        except Exception:  # noqa: BLE001 - a setup diagnostic; check_budget fails closed itself
            logger.warning("could not read today's usage for the setup check", exc_info=True)
            continue
        if blocked:
            warnings.append(unreported_cost_message(model, backend.provider))
    return warnings


# --- reporting (GET /api/usage) -------------------------------------------------------

_TOKEN_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
    "web_search_requests",
)


def _aggregates() -> list:
    cols = [
        func.count(LLMUsage.id).label("calls"),
        func.coalesce(func.sum(effective_cost), 0.0).label("cost_usd"),
        func.coalesce(
            func.sum(case((LLMUsage.backend.in_(KEY_BILLED_BACKENDS), effective_cost),
                          else_=0.0)),
            0.0,
        ).label("api_cost_usd"),
        func.coalesce(
            func.sum(case((effective_cost.is_(None), 1), else_=0)), 0
        ).label("unpriced_calls"),
    ]
    cols += [
        func.coalesce(func.sum(getattr(LLMUsage, name)), 0).label(name)
        for name in _TOKEN_FIELDS
    ]
    return cols


def _totals(row: Any) -> dict:
    out = {
        "calls": int(row.calls or 0),
        "cost_usd": float(row.cost_usd or 0.0),
        "api_cost_usd": float(row.api_cost_usd or 0.0),
        "unpriced_calls": int(row.unpriced_calls or 0),
    }
    out.update({name: int(getattr(row, name) or 0) for name in _TOKEN_FIELDS})
    return out


def cache_read_share(totals: dict) -> float | None:
    """Share of a group's input tokens (uncached + cache writes + cache reads) that were read
    from the prompt cache, 0..1; None when the group sent no input tokens."""
    read = totals["cache_read_input_tokens"]
    prompt = totals["input_tokens"] + totals["cache_creation_input_tokens"] + read
    return read / prompt if prompt else None


def usage_summary(session: Session, now: datetime | None = None) -> dict:
    """Totals per window, 30-day breakdowns by feature and model, and the budget state.

    Windows: "today" from local midnight; "last_7_days"/"last_30_days" are rolling.
    """
    now = now or datetime.now(timezone.utc)
    starts = {
        "today": local_day_start(now.astimezone()),
        "last_7_days": now - timedelta(days=7),
        "last_30_days": now - timedelta(days=30),
        "all_time": None,
    }
    totals: dict[str, dict] = {}
    for name, start in starts.items():
        stmt = select(*_aggregates())
        if start is not None:
            stmt = stmt.where(LLMUsage.created_at >= _db_time(start))
        totals[name] = _totals(session.exec(stmt).one())

    since = _db_time(starts["last_30_days"])

    def _breakdown(column) -> list[dict]:
        rows = session.exec(
            select(column.label("key"), *_aggregates())
            .where(LLMUsage.created_at >= since)
            .group_by(column)
        ).all()
        items = [{"key": r.key, **_totals(r)} for r in rows]
        items.sort(key=lambda i: (-i["cost_usd"], -i["calls"], str(i["key"])))
        return items

    by_feature = [{"feature": i.pop("key"), **i, "cache_read_share": cache_read_share(i)}
                  for i in _breakdown(LLMUsage.feature)]
    by_model = [{"model": i.pop("key"), **i} for i in _breakdown(LLMUsage.model)]
    for item in by_model:
        # The model catalog is the one source for the UI's "Experimental" label.
        item["experimental"] = model_catalog.is_experimental(item["model"])

    limit = settings.daily_budget_usd
    spent = totals["today"]["api_cost_usd"]
    budget = {
        "limit_usd": limit,
        "spent_today_usd": spent,
        "remaining_usd": None if limit is None else max(limit - spent, 0.0),
        "exceeded": limit is not None and spent >= limit,
    }
    return {"totals": totals, "by_feature": by_feature, "by_model": by_model,
            "budget": budget}
