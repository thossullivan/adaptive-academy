"""paper probe tables

Revision ID: d3b9f1c274ae
Revises: af45456b0fc5
Create Date: 2026-07-15
"""
import sqlalchemy as sa
from alembic import op

revision = "d3b9f1c274ae"
down_revision = "af45456b0fc5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "paperprobe",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=False),
        sa.Column("milestone_id", sa.Integer(), sa.ForeignKey("milestone.id"), nullable=False),
        sa.Column("paper_title", sa.String(), nullable=False, server_default=""),
        sa.Column("paper_url", sa.String(), nullable=False, server_default=""),
        sa.Column("paper_text", sa.String(), nullable=False, server_default=""),
        sa.Column("source", sa.String(), nullable=False, server_default="paste"),
        sa.Column("status", sa.String(), nullable=False, server_default="drafting"),
        sa.Column("questions", sa.JSON(), nullable=False, server_default="[]"),
        sa.Column("outcome", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "paperprobeanswer",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("probe_id", sa.Integer(), sa.ForeignKey("paperprobe.id"), nullable=False),
        sa.Column("question_index", sa.Integer(), nullable=False),
        sa.Column("content", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.add_column("assessment",
        sa.Column("paper_probe_id", sa.Integer(), nullable=True))
    op.add_column("agentevent",
        sa.Column("paper_probe_id", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("agentevent", "paper_probe_id")
    op.drop_column("assessment", "paper_probe_id")
    op.drop_table("paperprobeanswer")
    op.drop_table("paperprobe")
