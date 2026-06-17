import json
import os

import anthropic
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from adaptive_academy.api import (
    routes_conversations,
    routes_items,
    routes_practice,
    routes_story,
    routes_teach,
    routes_topics,
)
from adaptive_academy.api.routes_anchors import (
    concept_router as anchor_concept_router,
    topic_router as anchor_topic_router,
)
from adaptive_academy.api.routes_assess import router as assess_router
from adaptive_academy.api.routes_decay import (
    ops_router as decay_ops_router,
    topic_router as decay_topic_router,
)
from adaptive_academy.api.routes_remediate import router as remediate_router
from adaptive_academy.api.routes_retention import (
    card_router as retention_card_router,
    ops_router as retention_ops_router,
    topic_router as retention_topic_router,
)
from adaptive_academy.db import create_db_and_tables
from adaptive_academy.llm.types import AgentSDKError


def drop_api_key_if_agent_sdk() -> None:
    """Fully subscription-only in agent_sdk mode: drop ANTHROPIC_API_KEY so every Agent SDK
    subprocess (LLM, Researcher, Anchor) uses the Claude plan, not API credits — which lets
    the SDK clients skip per-call key juggling and run parallel/lock-free. Called from the
    startup hook (not import time) so merely importing this module never mutates the env."""
    if os.getenv("AA_LLM_BACKEND", "").lower() == "agent_sdk":
        os.environ.pop("ANTHROPIC_API_KEY", None)


def create_app() -> FastAPI:
    app = FastAPI(title="Adaptive Academy")
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
        else:
            # Surface the upstream message — it's actionable (e.g. "credit balance is
            # too low") and a vague "(BadRequestError)" hides the real cause.
            upstream = getattr(exc, "message", "") or str(exc)
            detail = f"LLM request failed upstream ({type(exc).__name__}): {upstream}"[:300]
        return JSONResponse(status_code=502, content={"detail": detail})

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

    app.include_router(routes_topics.router)
    app.include_router(routes_story.router)
    app.include_router(routes_conversations.router)
    app.include_router(routes_items.router)
    app.include_router(assess_router)
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
    return app


app = create_app()
