"""`aa seed` / `just seed`: add the demo topic (see adaptive_academy/demo.py). Idempotent."""

from sqlalchemy import Engine
from sqlmodel import Session

from adaptive_academy.db import create_db_and_tables, engine
from adaptive_academy.demo import ensure_demo


def seed(db_engine: Engine | None = None) -> None:
    if db_engine is None:
        create_db_and_tables()
        db_engine = engine
    with Session(db_engine) as session:
        topic, created = ensure_demo(session)
        if created:
            print(f"Added the demo topic {topic.id}: {topic.title!r}. "
                  f"Remove it from its dashboard, or with DELETE /api/demo/{topic.id}.")
        else:
            print(f"Demo topic already present ({topic.id}).")
