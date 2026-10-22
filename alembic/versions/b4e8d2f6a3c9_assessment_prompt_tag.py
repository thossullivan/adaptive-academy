"""assessment prompt_tag

Revision ID: b4e8d2f6a3c9
Revises: a7d3c5e9f2b1
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "b4e8d2f6a3c9"
down_revision = "a7d3c5e9f2b1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ADD COLUMN: `assessment` is populated and FK-referenced (baseline_assessment_id),
    # so it must never be recreated by batch mode. Existing rows stay NULL: which prompt
    # version graded them is unknown, and a guess would corrupt cross-version comparisons.
    op.add_column("assessment", sa.Column("prompt_tag", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("assessment", "prompt_tag")
