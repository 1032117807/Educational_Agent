"""attribute AI runs to organization members for usage administration

Revision ID: g18_ai_run_user_usage
Revises: g17_task_assignments
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g18_ai_run_user_usage"
down_revision: Union[str, None] = "g17_task_assignments"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("ai_runs", sa.Column("user_id", sa.String(length=36), nullable=True))
    op.create_index("ix_ai_runs_user_id", "ai_runs", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_ai_runs_user_id", table_name="ai_runs")
    op.drop_column("ai_runs", "user_id")
