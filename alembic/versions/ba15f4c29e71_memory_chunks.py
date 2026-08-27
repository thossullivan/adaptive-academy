"""memory chunks

Revision ID: ba15f4c29e71
Revises: d3b9f1c274ae
Create Date: 2026-08-25
"""

import sqlite3

import warnings

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import OperationalError

from adaptive_academy.db import FTS_DDL

revision = "ba15f4c29e71"
down_revision = "d3b9f1c274ae"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "chunk",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topic.id"), nullable=True),
        sa.Column(
            "concept_id",
            sa.Integer(),
            sa.ForeignKey("concept.id"),
            nullable=True,
        ),
        sa.Column("source_ref", sa.String(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(), nullable=False),
        sa.Column("text", sa.String(), nullable=False),
        sa.Column("context", sa.String(), nullable=False),
        sa.Column("content_hash", sa.String(), nullable=False),
        sa.Column("meta", sa.JSON(), nullable=False),
        sa.Column("source_mtime", sa.Float(), nullable=True),
        sa.Column("embedding_model", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint(
            "source_ref",
            "ordinal",
            name="uq_chunk_source_ref_ordinal",
        ),
        sa.Index("ix_chunk_kind_topic_id", "kind", "topic_id"),
        sa.Index("ix_chunk_kind_concept_id", "kind", "concept_id"),
        sa.Index("ix_chunk_source_ref", "source_ref"),
        sa.Index("ix_chunk_created_at", "created_at"),
    )
    op.create_table(
        "vaultlink",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("src_ref", sa.String(), nullable=False),
        sa.Column("dst_ref", sa.String(), nullable=False),
        sa.Column("dst_title", sa.String(), nullable=False),
        sa.Index("ix_vaultlink_src_ref", "src_ref"),
        sa.Index("ix_vaultlink_dst_ref", "dst_ref"),
    )
    _apply_fts_ddl(op.execute)


def _apply_fts_ddl(execute) -> bool:
    """Create the FTS5 objects when the SQLite build has FTS5; otherwise keep the plain
    tables and let the runtime degrade to the scripted retriever (no crash at upgrade)."""
    try:
        for statement in FTS_DDL:
            execute(statement)
    except OperationalError as exc:  # e.g. "no such module: fts5"
        warnings.warn(f"FTS5 unavailable; skipping chunk_fts: {exc}", stacklevel=2)
        return False
    return True


def downgrade() -> None:
    # sqlite-vec virtual tables require the optional extension during DROP. Hosts
    # without it skip these objects; ensure_vec removes stale rows after re-upgrade.
    try:
        import sqlite_vec

        connection = op.get_bind()
        raw_connection = connection.connection.driver_connection
        raw_connection.enable_load_extension(True)
        try:
            sqlite_vec.load(raw_connection)
        finally:
            raw_connection.enable_load_extension(False)
    except (ImportError, AttributeError, OSError, sqlite3.Error):
        pass
    else:
        op.execute("DROP TRIGGER IF EXISTS chunk_vec_ad")
        op.execute("DROP TABLE IF EXISTS chunk_vec")
    op.execute("DROP TRIGGER IF EXISTS chunk_au")
    op.execute("DROP TRIGGER IF EXISTS chunk_ad")
    op.execute("DROP TRIGGER IF EXISTS chunk_ai")
    op.execute("DROP TABLE IF EXISTS chunk_fts")
    op.drop_table("vaultlink")
    op.drop_table("chunk")
