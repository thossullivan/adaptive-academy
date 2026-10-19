"""llm usage table

Revision ID: e5b2a9c4d7f1
Revises: c9a7b3e1f204
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "e5b2a9c4d7f1"
down_revision = "c9a7b3e1f204"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "llmusage",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("backend", sa.String(), nullable=False),
        sa.Column("model", sa.String(), nullable=False),
        sa.Column("role", sa.String(), nullable=False, server_default=""),
        sa.Column("operation", sa.String(), nullable=False),
        sa.Column("feature", sa.String(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cache_creation_input_tokens", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("cache_read_input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("web_search_requests", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=True),
        sa.Index("ix_llmusage_created_at", "created_at"),
    )


def downgrade() -> None:
    op.drop_table("llmusage")
