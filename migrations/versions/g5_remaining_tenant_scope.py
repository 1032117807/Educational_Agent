"""add tenant scope to remaining SaaS-owned records"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "g5_remaining_tenant_scope"
down_revision: Union[str, None] = "g4_tenant_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TABLES = (
    "study_tasks", "questions", "review_items", "knowledge_points", "practice_sessions",
    "study_sessions", "study_goals", "question_attempts", "knowledge_point_drafts",
    "question_drafts", "subjective_grading_results", "error_analysis_results",
    "learning_plan_drafts", "adaptive_plan_drafts", "learning_report_snapshots",
    "research_runs", "agent_sessions", "agent_memories", "agent_workflows",
)

def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(length=36), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])

def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
