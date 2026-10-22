"""llmusage outcome, and an agentevent (kind, created_at) index

Revision ID: d6a1c3e5f7b9
Revises: c8e1f4a7b2d6
Create Date: 2026-10-22
"""

import sqlalchemy as sa
from alembic import op

revision = "d6a1c3e5f7b9"
down_revision = "c8e1f4a7b2d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Plain ADD COLUMN, never batch mode: llmusage is populated (every model call writes a
    # row). How each API-key call ended ("ok", "refusal", "cut_off", "empty",
    # "invalid_output"), for the Usage page's quality scorecard. A structured answer in the
    # wrong format was recorded nowhere before; existing rows stay NULL ("not recorded").
    op.add_column("llmusage", sa.Column("outcome", sa.String(), nullable=True))
    # The scorecard counts a few event kinds per time window. A plain CREATE INDEX: the
    # table, its rows and the foreign keys pointing at it are left as they are.
    op.create_index("ix_agentevent_kind_created_at", "agentevent", ["kind", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_agentevent_kind_created_at", table_name="agentevent")
    op.drop_column("llmusage", "outcome")
