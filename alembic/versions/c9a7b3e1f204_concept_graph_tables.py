"""concept graph tables

Revision ID: c9a7b3e1f204
Revises: ba15f4c29e71
Create Date: 2026-08-25
"""

import sqlalchemy as sa
from alembic import op

revision = "c9a7b3e1f204"
down_revision = "ba15f4c29e71"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "conceptedge",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "src_concept_id",
            sa.Integer(),
            sa.ForeignKey("concept.id"),
            nullable=False,
        ),
        sa.Column(
            "dst_concept_id",
            sa.Integer(),
            sa.ForeignKey("concept.id"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("origin_ref", sa.String(), nullable=False, server_default=""),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_until", sa.DateTime(), nullable=True),
        sa.Column("recorded_at", sa.DateTime(), nullable=False),
        sa.Index(
            "ix_conceptedge_src_concept_id_valid_until",
            "src_concept_id",
            "valid_until",
        ),
        sa.Index(
            "ix_conceptedge_dst_concept_id_valid_until",
            "dst_concept_id",
            "valid_until",
        ),
    )
    op.create_table(
        "chunkconcept",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "chunk_id",
            sa.Integer(),
            sa.ForeignKey("chunk.id"),
            nullable=False,
        ),
        sa.Column(
            "concept_id",
            sa.Integer(),
            sa.ForeignKey("concept.id"),
            nullable=False,
        ),
        sa.Column("hits", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint(
            "chunk_id",
            "concept_id",
            name="uq_chunkconcept_chunk_id_concept_id",
        ),
    )
    op.create_table(
        "topicsuggestion",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "program_id",
            sa.Integer(),
            sa.ForeignKey("program.id"),
            nullable=True,
        ),
        sa.Column("title", sa.String(), nullable=False),
        sa.Column("rationale", sa.String(), nullable=False),
        sa.Column("candidate_kind", sa.String(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("score", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("status", sa.String(), nullable=False, server_default="proposed"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Index("ix_topicsuggestion_status_program_id", "status", "program_id"),
    )


def downgrade() -> None:
    op.drop_table("topicsuggestion")
    op.drop_table("chunkconcept")
    op.drop_table("conceptedge")
