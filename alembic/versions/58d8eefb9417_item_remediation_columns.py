"""item remediation columns

Revision ID: 58d8eefb9417
Revises: 8b27f2ac6c62
Create Date: 2026-06-16
"""
from alembic import op
import sqlalchemy as sa

revision = "58d8eefb9417"
down_revision = "8b27f2ac6c62"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("item", sa.Column("added_by", sa.String(), nullable=False,
                                    server_default="curriculum"))
    op.add_column("item", sa.Column("remediation_key", sa.String(), nullable=False,
                                    server_default=""))


def downgrade() -> None:
    op.drop_column("item", "remediation_key")
    op.drop_column("item", "added_by")
