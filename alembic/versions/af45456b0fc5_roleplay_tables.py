"""roleplay tables

Revision ID: af45456b0fc5
Revises: f71fe80890b6
Create Date: 2026-07-15
"""
import sqlalchemy as sa
from alembic import op

revision = "af45456b0fc5"
down_revision = "f71fe80890b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "roleplaysession",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=False),
        sa.Column("milestone_id", sa.Integer(), sa.ForeignKey("milestone.id"), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="briefing"),
        sa.Column("persona_brief", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("outcome", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "roleplayturn",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("roleplaysession.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.add_column("assessment",
        sa.Column("roleplay_session_id", sa.Integer(), nullable=True))
    op.add_column("agentevent",
        sa.Column("roleplay_session_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agentevent", "roleplay_session_id")
    op.drop_column("assessment", "roleplay_session_id")
    op.drop_table("roleplayturn")
    op.drop_table("roleplaysession")
