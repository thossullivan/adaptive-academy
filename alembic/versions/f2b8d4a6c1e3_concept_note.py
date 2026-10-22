"""concept_note table, and message.reveals_solution (concept notebooks)

Revision ID: f2b8d4a6c1e3
Revises: e7c4a2b9d1f3
Create Date: 2026-10-23
"""

import sqlalchemy as sa
from alembic import op

revision = "f2b8d4a6c1e3"
down_revision = "e7c4a2b9d1f3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # A new table: the learner's own notes, one row per concept.
    op.create_table(
        "concept_note",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("concept_id", sa.Integer(), sa.ForeignKey("concept.id"), nullable=False,
                  unique=True),
        sa.Column("body", sa.String(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    # Plain ADD COLUMN, never batch mode: message is populated and FK-referenced (attempt).
    # Existing messages stay NULL: an old reveal can't be told from a hint after the fact.
    op.add_column("message", sa.Column("reveals_solution", sa.Boolean(), nullable=True))


def downgrade() -> None:
    op.drop_table("concept_note")
    op.drop_column("message", "reveals_solution")
