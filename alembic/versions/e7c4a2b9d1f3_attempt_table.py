"""attempt table, and message.is_attempt (the Attempt button)

Revision ID: e7c4a2b9d1f3
Revises: d6a1c3e5f7b9
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "e7c4a2b9d1f3"
down_revision = "d6a1c3e5f7b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A new table: one row per message the learner submitted as an attempt.
    op.create_table(
        "attempt",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("conversation_id", sa.Integer(), sa.ForeignKey("conversation.id"),
                  nullable=False),
        sa.Column("concept_id", sa.Integer(), sa.ForeignKey("concept.id"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("message.id"), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    # Plain ADD COLUMN, never batch mode: message is populated and the new table points at it.
    # Existing messages stay NULL (nothing is marked as an attempt after the fact).
    op.add_column("message", sa.Column("is_attempt", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_table("attempt")
    op.drop_column("message", "is_attempt")
