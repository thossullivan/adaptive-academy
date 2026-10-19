"""Token/cost accounting for every real model call, and the daily spending limit.

Recording: each LLM client calls `record_usage(...)` right after its model call returns. The
row goes through the one bounded trace writer (engine/trace_writer.py), so it is written in
its own short session off the request thread — never inside the caller's transaction, never
waiting on SQLite's write lock — and any failure is logged and swallowed: usage accounting
must never break a call that already succeeded (and was already billed).

Feature attribution: a contextvar holds a short label for the API route that triggered the
call (set by a FastAPI dependency in api/app.py, from the matched route template), so engine
code needs no extra parameters. Non-request callers (CLI, scripts) record feature=NULL.

Budget: `check_budget()` runs before every API-key (backend="anthropic") call. When
AA_DAILY_BUDGET_USD is set and today's recorded API-key spend already meets or exceeds it, it
raises BudgetExceededError (→ HTTP 429). "Today" is the server's local calendar day (UTC in
the Docker image unless TZ is set). A single call can overshoot the limit — the check runs
before the call, and the call's cost is only known after it. Agent SDK calls are billed to
the Claude subscription, not the key, so they are recorded but never blocked.
"""

from __future__ import annotations

import contextvars
import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, select

from adaptive_academy.engine.trace_writer import TRACE_WRITER
from adaptive_academy.llm import pricing
from adaptive_academy.models import LLMUsage
from adaptive_academy.settings import settings

logger = logging.getLogger(__name__)

BACKEND_ANTHROPIC = "anthropic"
BACKEND_AGENT_SDK = "agent_sdk"


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
        TRACE_WRITER.submit(bind, [row])
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
    """Recorded API-key spend since local midnight. Unknown-price calls count as $0."""
    bind = get_usage_bind()
    if bind is None:
        return 0.0
    start = _db_time(local_day_start(now))
    with Session(bind) as session:
        total = session.exec(
            select(func.coalesce(func.sum(LLMUsage.cost_usd), 0.0)).where(
                LLMUsage.created_at >= start,
                LLMUsage.backend == BACKEND_ANTHROPIC,
            )
        ).one()
        _close_read_session(session, bind)
    return float(total or 0.0)


def check_budget() -> None:
    """Raise BudgetExceededError if today's API-key spend meets the configured limit.

    Fails open: if today's spend can't be read, the call proceeds and a warning is logged
    — a broken usage store must not take every LLM feature down with it.
    """
    limit = settings.daily_budget_usd
    if limit is None:
        return
    try:
        spent = spent_today_usd()
    except Exception:  # noqa: BLE001
        logger.warning("daily budget check skipped: could not read today's spend",
                       exc_info=True)
        return
    if spent >= limit:
        raise BudgetExceededError(spent, limit)


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
        func.coalesce(func.sum(LLMUsage.cost_usd), 0.0).label("cost_usd"),
        func.coalesce(
            func.sum(case((LLMUsage.backend == BACKEND_ANTHROPIC, LLMUsage.cost_usd), else_=0.0)),
            0.0,
        ).label("api_cost_usd"),
        func.coalesce(
            func.sum(case((LLMUsage.cost_usd.is_(None), 1), else_=0)), 0
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

    by_feature = [{"feature": i.pop("key"), **i} for i in _breakdown(LLMUsage.feature)]
    by_model = [{"model": i.pop("key"), **i} for i in _breakdown(LLMUsage.model)]

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
