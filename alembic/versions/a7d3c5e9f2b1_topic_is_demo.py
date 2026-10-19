"""topic is_demo flag

Revision ID: a7d3c5e9f2b1
Revises: e5b2a9c4d7f1
Create Date: 2026-10-19
"""

import sqlalchemy as sa
from alembic import op

revision = "a7d3c5e9f2b1"
down_revision = "e5b2a9c4d7f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ADD COLUMN: `topic` is populated and FK-referenced, so it must never be recreated
    # by batch mode. Existing topics are real ones, hence the false default.
    op.add_column(
        "topic",
        sa.Column("is_demo", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade() -> None:
    op.drop_column("topic", "is_demo")
