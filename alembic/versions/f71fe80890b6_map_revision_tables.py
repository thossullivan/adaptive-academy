"""map revision tables

Revision ID: f71fe80890b6
Revises: 5e252d8109c0
Create Date: 2026-07-10 09:19:48.626207

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f71fe80890b6'
down_revision: Union[str, Sequence[str], None] = '5e252d8109c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "maprevision",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("program_id", sa.Integer(), sa.ForeignKey("program.id"), nullable=False),
        sa.Column("map_health", sa.String(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "mapchange",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("revision_id", sa.Integer(), sa.ForeignKey("maprevision.id"), nullable=False),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("why", sa.String(), nullable=False, server_default=""),
        sa.Column("source_urls", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    with op.batch_alter_table("milestone") as batch:
        batch.add_column(sa.Column("archived", sa.Boolean(), nullable=False,
                                   server_default=sa.false()))
    with op.batch_alter_table("programtopiclink") as batch:
        batch.add_column(sa.Column("added_by", sa.String(), nullable=False,
                                   server_default="research"))


def downgrade() -> None:
    with op.batch_alter_table("programtopiclink") as batch:
        batch.drop_column("added_by")
    with op.batch_alter_table("milestone") as batch:
        batch.drop_column("archived")
    op.drop_table("mapchange")
    op.drop_table("maprevision")
