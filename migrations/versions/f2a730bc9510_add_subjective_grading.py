"""add subjective grading

Revision ID: f2a730bc9510
Revises: e8c531a2f420
Create Date: 2026-07-30 15:00:00
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f2a730bc9510"
down_revision: Union[str, None] = "e8c531a2f420"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "subjective_grading_results",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ai_run_id", sa.Integer(), nullable=False),
        sa.Column("attempt_id", sa.Integer(), nullable=False),
        sa.Column("question_id", sa.Integer(), nullable=False),
        sa.Column("total_score", sa.Float(), nullable=False),
        sa.Column("max_score", sa.Float(), nullable=False),
        sa.Column("rubric_json", sa.Text(), nullable=False),
        sa.Column("strengths_json", sa.Text(), nullable=False),
        sa.Column("missing_points_json", sa.Text(), nullable=False),
        sa.Column("errors_json", sa.Text(), nullable=False),
        sa.Column("feedback", sa.Text(), nullable=False),
        sa.Column("improved_answer", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("human_score", sa.Float(), nullable=True),
        sa.Column("human_note", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["ai_run_id"], ["ai_runs.id"]),
        sa.ForeignKeyConstraint(["attempt_id"], ["question_attempts.id"]),
        sa.ForeignKeyConstraint(["question_id"], ["questions.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ai_run_id"),
    )
    op.create_index(
        "ix_subjective_grading_results_ai_run_id",
        "subjective_grading_results", ["ai_run_id"], unique=True,
    )
    op.create_index(
        "ix_subjective_grading_results_attempt_id",
        "subjective_grading_results", ["attempt_id"],
    )
    op.create_index(
        "ix_subjective_grading_results_question_id",
        "subjective_grading_results", ["question_id"],
    )
    op.create_index(
        "ix_subjective_grading_results_status",
        "subjective_grading_results", ["status"],
    )
    op.create_table(
        "subjective_grading_citations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("grading_result_id", sa.Integer(), nullable=False),
        sa.Column("chunk_id", sa.Integer(), nullable=False),
        sa.Column("citation_number", sa.Integer(), nullable=False),
        sa.Column("quote_text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["chunk_id"], ["document_chunks.id"]),
        sa.ForeignKeyConstraint(
            ["grading_result_id"], ["subjective_grading_results.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "grading_result_id", "chunk_id", name="uq_grading_result_chunk"
        ),
    )
    op.create_index(
        "ix_subjective_grading_citations_grading_result_id",
        "subjective_grading_citations", ["grading_result_id"],
    )
    op.create_index(
        "ix_subjective_grading_citations_chunk_id",
        "subjective_grading_citations", ["chunk_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_subjective_grading_citations_chunk_id",
        table_name="subjective_grading_citations",
    )
    op.drop_index(
        "ix_subjective_grading_citations_grading_result_id",
        table_name="subjective_grading_citations",
    )
    op.drop_table("subjective_grading_citations")
    op.drop_index(
        "ix_subjective_grading_results_status",
        table_name="subjective_grading_results",
    )
    op.drop_index(
        "ix_subjective_grading_results_question_id",
        table_name="subjective_grading_results",
    )
    op.drop_index(
        "ix_subjective_grading_results_attempt_id",
        table_name="subjective_grading_results",
    )
    op.drop_index(
        "ix_subjective_grading_results_ai_run_id",
        table_name="subjective_grading_results",
    )
    op.drop_table("subjective_grading_results")
