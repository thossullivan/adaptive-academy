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
    # Plain ADD COLUMN, NOT batch_alter_table. Batch mode recreates the table
    # (copy -> DROP old -> rename); dropping a POPULATED `milestone` while
    # `PRAGMA foreign_keys=ON` fails because live `programtopiclink` rows
    # reference it. A direct ADD COLUMN with a server_default needs no
    # recreation and works on populated, referenced tables. (Empty test DBs
    # never surfaced this — see tests/test_migration_populated.py.)
    op.add_column("milestone", sa.Column("archived", sa.Boolean(), nullable=False,
                                         server_default=sa.false()))
    op.add_column("programtopiclink", sa.Column("added_by", sa.String(), nullable=False,
                                                server_default="research"))


def downgrade() -> None:
    # Native ALTER TABLE ... DROP COLUMN (SQLite >= 3.35); no table recreation,
    # so no inbound-FK hazard on populated tables.
    op.drop_column("programtopiclink", "added_by")
    op.drop_column("milestone", "archived")
    op.drop_table("mapchange")
    op.drop_table("maprevision")
