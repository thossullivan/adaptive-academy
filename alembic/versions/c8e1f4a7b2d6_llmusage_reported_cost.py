"""llmusage reported_cost_usd

Revision ID: c8e1f4a7b2d6
Revises: b4e8d2f6a3c9
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "c8e1f4a7b2d6"
down_revision = "b4e8d2f6a3c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ADD COLUMN, never batch mode: llmusage is populated (every model call writes a
    # row). What the service reported charging (OpenRouter's usage.cost); existing rows stay
    # NULL, since the Anthropic API reports no cost and their list-price cost_usd still holds.
    op.add_column("llmusage", sa.Column("reported_cost_usd", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("llmusage", "reported_cost_usd")
