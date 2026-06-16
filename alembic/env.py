from logging.config import fileConfig

from alembic import context
from sqlmodel import SQLModel

import adaptive_academy.models  # noqa: F401  (register tables)
from adaptive_academy.db import engine

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)
target_metadata = SQLModel.metadata


def run_migrations_online() -> None:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,  # SQLite-safe ALTER TABLE
        )
        with context.begin_transaction():
            context.run_migrations()


run_migrations_online()
