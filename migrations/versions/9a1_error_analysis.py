"""add error analysis results"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "9a1_error_analysis"
down_revision: Union[str, None] = "f2a730bc9510"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "error_analysis_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ai_run_id", sa.Integer(), sa.ForeignKey("ai_runs.id"), nullable=False),
        sa.Column("attempt_id", sa.Integer(), sa.ForeignKey("question_attempts.id"), nullable=False),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), sa.ForeignKey("knowledge_points.id"), nullable=True),
        sa.Column("error_types_json", sa.Text(), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("explanation", sa.Text(), nullable=False),
        sa.Column("missing_knowledge_json", sa.Text(), nullable=False),
        sa.Column("recommended_exercises_json", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("needs_human_review", sa.Boolean(), nullable=False),
        sa.Column("human_confirmed", sa.Boolean(), nullable=False),
        sa.Column("human_note", sa.Text(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_error_analysis_attempt_id", "error_analysis_results", ["attempt_id"])
    op.create_index("ix_error_analysis_status", "error_analysis_results", ["status"])


def downgrade() -> None:
    op.drop_index("ix_error_analysis_status", table_name="error_analysis_results")
    op.drop_index("ix_error_analysis_attempt_id", table_name="error_analysis_results")
    op.drop_table("error_analysis_results")
