"""add knowledge extraction fields and draft citations

Revision ID: c3f9a821d104
Revises: 7d23839ea774
Create Date: 2026-07-29 18:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c3f9a821d104"
down_revision: Union[str, None] = "7d23839ea774"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_point_drafts") as batch:
        batch.add_column(sa.Column("category", sa.String(30), nullable=False, server_default="概念"))
        batch.add_column(sa.Column("difficulty", sa.Integer(), nullable=False, server_default="3"))
        batch.add_column(sa.Column("confidence", sa.Float(), nullable=False, server_default="0"))

    with op.batch_alter_table("knowledge_points") as batch:
        batch.add_column(sa.Column("category", sa.String(30), nullable=False, server_default="概念"))
        batch.add_column(sa.Column("definition", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("formula", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("prerequisites_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("related_points_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("common_mistakes_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("difficulty", sa.Integer(), nullable=False, server_default="3"))
        batch.add_column(sa.Column("importance", sa.Integer(), nullable=False, server_default="3"))
        batch.add_column(sa.Column("confidence", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("source", sa.String(20), nullable=False, server_default="user"))

    op.create_table(
        "knowledge_point_draft_citations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("draft_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("quote_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"]),
        sa.ForeignKeyConstraint(["draft_id"], ["knowledge_point_drafts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("draft_id", "chunk_id", name="uq_knowledge_draft_chunk"),
    )
    op.create_index(
        "ix_knowledge_point_draft_citations_draft_id",
        "knowledge_point_draft_citations",
        ["draft_id"],
    )
    op.create_index(
        "ix_knowledge_point_draft_citations_chunk_id",
        "knowledge_point_draft_citations",
        ["chunk_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_point_draft_citations_chunk_id", table_name="knowledge_point_draft_citations")
    op.drop_index("ix_knowledge_point_draft_citations_draft_id", table_name="knowledge_point_draft_citations")
    op.drop_table("knowledge_point_draft_citations")
    with op.batch_alter_table("knowledge_points") as batch:
        for name in (
            "source", "confidence", "importance", "difficulty",
            "common_mistakes_json", "related_points_json",
            "prerequisites_json", "formula", "definition", "category",
        ):
            batch.drop_column(name)
    with op.batch_alter_table("knowledge_point_drafts") as batch:
        batch.drop_column("confidence")
        batch.drop_column("difficulty")
        batch.drop_column("category")
