"""program layer tables

Revision ID: 5e252d8109c0
Revises: 58d8eefb9417
Create Date: 2026-07-09 18:06:44.421827

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5e252d8109c0'
down_revision: Union[str, Sequence[str], None] = '58d8eefb9417'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "program",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("goal_statement", sa.String(), nullable=False, server_default=""),
        sa.Column("status", sa.String(), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "programintent",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=False, unique=True),
        sa.Column("target_depth", sa.String(), nullable=False, server_default=""),
        sa.Column("prior_knowledge", sa.String(), nullable=False, server_default=""),
        sa.Column("weekly_time_budget", sa.String(), nullable=False, server_default=""),
        sa.Column("horizon", sa.String(), nullable=False, server_default=""),
        sa.Column("focus_area", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "milestone",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=False),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("success_criteria", sa.String(), nullable=False, server_default=""),
        sa.Column("order_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("gate_status", sa.String(), nullable=False, server_default="open"),
        sa.Column("depends_on", sa.JSON(), nullable=False),
        sa.Column("override_reason", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "programtopiclink",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("milestone_id", sa.Integer(), sa.ForeignKey("milestone.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topic.id"), nullable=True),
        sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        sa.Column("proposed_title", sa.String(), nullable=False, server_default=""),
        sa.Column("why", sa.String(), nullable=False, server_default=""),
        sa.Column("sources", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "conceptalias",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=False),
        sa.Column("canonical_name", sa.String(), nullable=False),
        sa.Column("concept_id", sa.Integer(), sa.ForeignKey("concept.id"), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("agentevent", schema=None) as batch_op:
        batch_op.add_column(sa.Column("program_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key("fk_agentevent_program_id", "program", ["program_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("agentevent", schema=None) as batch_op:
        batch_op.drop_constraint("fk_agentevent_program_id", type_="foreignkey")
        batch_op.drop_column("program_id")
    op.drop_table("conceptalias")
    op.drop_table("programtopiclink")
    op.drop_table("milestone")
    op.drop_table("programintent")
    op.drop_table("program")
