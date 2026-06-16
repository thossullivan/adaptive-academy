from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from adaptive_academy.api import routes_conversations, routes_items, routes_topics
from adaptive_academy.api.routes_assess import router as assess_router
from adaptive_academy.api.routes_remediate import router as remediate_router
from adaptive_academy.api.routes_retention import (
    card_router as retention_card_router,
    ops_router as retention_ops_router,
    topic_router as retention_topic_router,
)
from adaptive_academy.db import create_db_and_tables


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
        create_db_and_tables()

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok"}

    app.include_router(routes_topics.router)
    app.include_router(routes_conversations.router)
    app.include_router(routes_items.router)
    app.include_router(assess_router)
    app.include_router(remediate_router)
    app.include_router(retention_card_router)
    app.include_router(retention_topic_router)
    app.include_router(retention_ops_router)
    return app


app = create_app()
