"""add learning plan drafts"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "a31_learning_plan_drafts"
down_revision: Union[str, None] = "9a1_error_analysis"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_table(
        "learning_plan_drafts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("ai_run_id", sa.Integer(), sa.ForeignKey("ai_runs.id"), nullable=False),
        sa.Column("goal_id", sa.Integer(), sa.ForeignKey("study_goals.id"), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("risks_json", sa.Text(), nullable=False),
        sa.Column("daily_minutes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("ai_run_id"),
    )
    op.create_index("ix_learning_plan_drafts_goal_id", "learning_plan_drafts", ["goal_id"])
    op.create_index("ix_learning_plan_drafts_status", "learning_plan_drafts", ["status"])
    op.create_table(
        "learning_plan_draft_tasks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("draft_id", sa.Integer(), sa.ForeignKey("learning_plan_drafts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(160), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False),
        sa.Column("task_type", sa.String(30), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=True),
        sa.Column("knowledge_point_id", sa.Integer(), sa.ForeignKey("knowledge_points.id"), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
    )
    op.create_index("ix_learning_plan_draft_tasks_draft_id", "learning_plan_draft_tasks", ["draft_id"])

def downgrade() -> None:
    op.drop_index("ix_learning_plan_draft_tasks_draft_id", table_name="learning_plan_draft_tasks")
    op.drop_table("learning_plan_draft_tasks")
    op.drop_index("ix_learning_plan_drafts_status", table_name="learning_plan_drafts")
    op.drop_index("ix_learning_plan_drafts_goal_id", table_name="learning_plan_drafts")
    op.drop_table("learning_plan_drafts")
