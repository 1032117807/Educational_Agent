"""add question draft citations

Revision ID: e8c531a2f420
Revises: d6a77b92e310
Create Date: 2026-07-30 10:00:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e8c531a2f420"
down_revision: Union[str, None] = "d6a77b92e310"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "question_draft_citations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("question_draft_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("citation_number", sa.Integer(), nullable=False),
        sa.Column("quote_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_draft_id"],
            ["question_drafts.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["document_chunks.id"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "question_draft_id",
            "chunk_id",
            name="uq_question_draft_chunk",
        ),
    )

    op.create_index(
        "ix_question_draft_citations_question_draft_id",
        "question_draft_citations",
        ["question_draft_id"],
    )

    op.create_index(
        "ix_question_draft_citations_chunk_id",
        "question_draft_citations",
        ["chunk_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_question_draft_citations_chunk_id",
        table_name="question_draft_citations",
    )

    op.drop_index(
        "ix_question_draft_citations_question_draft_id",
        table_name="question_draft_citations",
    )

    op.drop_table("question_draft_citations")