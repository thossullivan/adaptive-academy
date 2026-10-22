import json
import logging
import os
from pathlib import Path

import anthropic
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from adaptive_academy.settings import settings

from adaptive_academy.api import (
    routes_conversations,
    routes_deliverables,
    routes_demo,
    routes_export,
    routes_items,
    routes_memory,
    routes_momentum,
    routes_notebook,
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
from adaptive_academy.db import create_db_and_tables, db_revision_problem
from adaptive_academy.llm.backends import (
    AGENT_SDK_IN_CONTAINER_DETAIL,
    agent_sdk_unavailable,
    backend_setting_problem,
    use_agent_sdk,
)
from adaptive_academy.llm.errors import describe_llm_error
from adaptive_academy.llm.keys import MissingAPIKeyError
from adaptive_academy.llm.types import AgentSDKError, StructuredOutputError
from adaptive_academy.llm.usage import BudgetExceededError, feature_from_route, set_feature

logger = logging.getLogger(__name__)

# Every failure a model call can raise, mapped by llm/errors.py to {detail, category}:
# upstream API errors, a missing key (503), the daily limit (429), Agent SDK failures,
# structured output with no usable tool call, and unparseable model JSON. (Request-body JSON
# is validated by FastAPI before reaching handlers, so a JSONDecodeError here is from parsing
# model output.)
_LLM_FAILURES = (
    anthropic.APIError,
    MissingAPIKeyError,
    BudgetExceededError,
    AgentSDKError,
    StructuredOutputError,
    json.JSONDecodeError,
)


def llm_failure_response(request: Request, exc: Exception) -> JSONResponse:
    """A failed model call → legible JSON instead of a bare 500: `detail` says what happened
    and what to do, `category` is a stable key. Covers every LLM-backed route at once. Run
    guards are context managers, so they are already released."""
    failure = describe_llm_error(exc)
    return JSONResponse(status_code=failure.status_code,
                        content={"detail": failure.detail, "category": failure.category})


def drop_api_key_if_agent_sdk() -> None:
    """Fully subscription-only in agent_sdk mode: drop ANTHROPIC_API_KEY so every Agent SDK
    subprocess (LLM, Researcher, Anchor) uses the Claude plan, not API credits — which lets
    the SDK clients skip per-call key juggling and run parallel/lock-free. Called from the
    startup hook (not import time) so merely importing this module never mutates the env."""
    if use_agent_sdk():
        os.environ.pop("ANTHROPIC_API_KEY", None)


def setup_problems() -> list[str]:
    """Configuration that will make model calls (or their accounting) fail, in plain words:
    a mistyped AA_LLM_BACKEND, agent_sdk inside the container, a database behind the code."""
    problems = [backend_setting_problem(), db_revision_problem()]
    if agent_sdk_unavailable():
        problems.append(AGENT_SDK_IN_CONTAINER_DETAIL)
    return [p for p in problems if p]


def log_setup_problems() -> None:
    """Startup: say each problem once in the API log, where `just api` / `just logs` show it."""
    for problem in setup_problems():
        logger.warning("setup: %s", problem)


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
        log_setup_problems()

    for exc_class in _LLM_FAILURES:
        app.add_exception_handler(exc_class, llm_failure_response)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(routes_setup.router)
    app.include_router(routes_topics.router)
    app.include_router(routes_demo.router)
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
    app.include_router(routes_notebook.router)
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
