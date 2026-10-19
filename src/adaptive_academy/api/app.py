import json
import os
import re
from pathlib import Path

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from adaptive_academy.settings import settings

from adaptive_academy.api import (
    routes_conversations,
    routes_deliverables,
    routes_export,
    routes_items,
    routes_memory,
    routes_momentum,
    routes_practice,
    routes_setup,
    routes_story,
    routes_teach,
    routes_topics,
    routes_usage,
    routes_vault,
)
from adaptive_academy.api.routes_anchors import (
    concept_router as anchor_concept_router,
    topic_router as anchor_topic_router,
)
from adaptive_academy.api.routes_assess import router as assess_router
from adaptive_academy.api.routes_graph import router as graph_router
from adaptive_academy.api.routes_decay import (
    ops_router as decay_ops_router,
    topic_router as decay_topic_router,
)
from adaptive_academy.api.routes_paper_probe import router as paper_probe_router
from adaptive_academy.api.routes_programs import router as programs_router
from adaptive_academy.api.routes_remediate import router as remediate_router
from adaptive_academy.api.routes_retention import (
    card_router as retention_card_router,
    ops_router as retention_ops_router,
    topic_router as retention_topic_router,
)
from adaptive_academy.api.routes_roleplay import router as roleplay_router
from adaptive_academy.api.routes_scout import router as scout_router
from adaptive_academy.db import create_db_and_tables
from adaptive_academy.llm.keys import MissingAPIKeyError
from adaptive_academy.llm.registry import MODEL_ENV_VARS, ROLES, get_model
from adaptive_academy.llm.types import AgentSDKError
from adaptive_academy.llm.usage import BudgetExceededError, feature_from_route, set_feature


# Upstream says e.g. "model: claude-foo-1". Only an id-shaped token is lifted, so nothing
# else from the upstream text (which we don't control) is echoed back.
_MODEL_IN_MESSAGE = re.compile(r"\bmodel:\s*([A-Za-z0-9][A-Za-z0-9._:@/-]{0,99})")


def model_unavailable_detail(exc: anthropic.NotFoundError) -> str:
    """A legible fix for a model the API doesn't recognise: name the id and the setting."""
    match = _MODEL_IN_MESSAGE.search(getattr(exc, "message", "") or str(exc))
    model = match.group(1).rstrip(".,;:'\"") if match else None
    env_vars = [MODEL_ENV_VARS[role] for role in ROLES if model and get_model(role) == model]
    if not env_vars:
        env_vars = [MODEL_ENV_VARS[role] for role in ROLES]
    setting = env_vars[0] if len(env_vars) == 1 else f"{env_vars[0]} (or {', '.join(env_vars[1:])})"
    subject = f"The model '{model}'" if model else "The configured model"
    return (f"{subject} is not available to this API key. "
            f"Set {setting} in .env to a current model and restart the API.")


def drop_api_key_if_agent_sdk() -> None:
    """Fully subscription-only in agent_sdk mode: drop ANTHROPIC_API_KEY so every Agent SDK
    subprocess (LLM, Researcher, Anchor) uses the Claude plan, not API credits — which lets
    the SDK clients skip per-call key juggling and run parallel/lock-free. Called from the
    startup hook (not import time) so merely importing this module never mutates the env."""
    if os.getenv("AA_LLM_BACKEND", "").lower() == "agent_sdk":
        os.environ.pop("ANTHROPIC_API_KEY", None)


def _mount_spa(app: FastAPI) -> None:
    """Serve the built SvelteKit SPA when a build directory exists (i.e. in the
    container image). Registered last so every /api route wins; unknown /api paths
    stay 404 rather than returning index.html to a confused API client."""
    dist = Path(settings.frontend_dist).resolve()
    index = dist / "index.html"
    if not index.is_file():
        return

    @app.get("/{full_path:path}", include_in_schema=False)
    def spa(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404)
        candidate = (dist / full_path).resolve()
        if full_path and candidate.is_relative_to(dist) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)


async def _label_llm_usage(request: Request) -> None:
    """Tag any model call this request makes with a feature label from the matched route
    (e.g. "/api/topics/{topic_id}/research" → "research"), via a contextvar, so engine code
    needs no extra parameters. Async on purpose: it runs in the request's own context, which
    the sync endpoint's worker thread then inherits."""
    route = request.scope.get("route")
    set_feature(feature_from_route(getattr(route, "path", None)))


def create_app() -> FastAPI:
    app = FastAPI(title="Adaptive Academy", dependencies=[Depends(_label_llm_usage)])
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.on_event("startup")
    def _startup() -> None:
        drop_api_key_if_agent_sdk()
        create_db_and_tables()

    @app.exception_handler(anthropic.APIError)
    def _llm_error(request: Request, exc: anthropic.APIError) -> JSONResponse:
        """Turn upstream LLM failures into a legible 502 instead of a bare 500.

        Covers every LLM-backed route at once (tutor/assess/remediate/research/anchors).
        """
        if isinstance(exc, anthropic.AuthenticationError):
            detail = "LLM authentication failed — check ANTHROPIC_API_KEY in .env"
        elif isinstance(exc, anthropic.RateLimitError):
            detail = "LLM rate limit hit — wait a moment and retry"
        elif isinstance(exc, anthropic.NotFoundError):
            # 404 not_found_error is what an unknown/retired model id returns.
            detail = model_unavailable_detail(exc)
        else:
            # Surface the upstream message — it's actionable (e.g. "credit balance is
            # too low") and a vague "(BadRequestError)" hides the real cause.
            upstream = getattr(exc, "message", "") or str(exc)
            detail = f"LLM request failed upstream ({type(exc).__name__}): {upstream}"[:300]
        return JSONResponse(status_code=502, content={"detail": detail})

    @app.exception_handler(MissingAPIKeyError)
    def _missing_key(request: Request, exc: MissingAPIKeyError) -> JSONResponse:
        """No ANTHROPIC_API_KEY (unset/blank/placeholder) → a legible 503 telling a first-run
        user exactly how to fix it, instead of a bare KeyError 500. Raised when an LLM-backed
        route builds its Anthropic client, so it covers every such route at once."""
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(BudgetExceededError)
    def _budget_exceeded(request: Request, exc: BudgetExceededError) -> JSONResponse:
        """AA_DAILY_BUDGET_USD reached → 429 saying what was spent, the limit, and how to
        raise it. Raised before the call that would have spent more; calls this request
        already made (e.g. earlier research angles) were billed and recorded."""
        return JSONResponse(status_code=429, content={"detail": str(exc)})

    @app.exception_handler(AgentSDKError)
    def _agent_sdk_error(request: Request, exc: AgentSDKError) -> JSONResponse:
        """Agent SDK (subscription-backend) failures → legible 502, like APIError."""
        return JSONResponse(status_code=502,
                            content={"detail": f"Agent SDK request failed: {exc}"[:300]})

    @app.exception_handler(json.JSONDecodeError)
    def _bad_llm_json(request: Request, exc: json.JSONDecodeError) -> JSONResponse:
        """An LLM returned unparseable/truncated JSON — surface it as a retryable 502
        rather than a bare 500. (Request-body JSON is validated by FastAPI before
        reaching handlers, so a JSONDecodeError here is from parsing model output.)"""
        return JSONResponse(status_code=502,
                            content={"detail": "LLM returned malformed JSON — please retry"})

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(routes_setup.router)
    app.include_router(routes_topics.router)
    app.include_router(routes_story.router)
    app.include_router(routes_conversations.router)
    app.include_router(routes_items.router)
    app.include_router(assess_router)
    app.include_router(graph_router)
    app.include_router(remediate_router)
    app.include_router(retention_card_router)
    app.include_router(retention_topic_router)
    app.include_router(retention_ops_router)
    app.include_router(anchor_topic_router)
    app.include_router(anchor_concept_router)
    app.include_router(decay_topic_router)
    app.include_router(decay_ops_router)
    app.include_router(routes_practice.router)
    app.include_router(routes_teach.router)
    app.include_router(routes_deliverables.router)
    app.include_router(routes_vault.router)
    app.include_router(routes_export.router)
    app.include_router(routes_memory.router)
    app.include_router(routes_momentum.router)
    app.include_router(programs_router)
    app.include_router(scout_router)
    app.include_router(roleplay_router)
    app.include_router(paper_probe_router)
    app.include_router(routes_usage.router)
    _mount_spa(app)
    return app


app = create_app()
