"""add adaptive learning plan drafts

Revision ID: e3_adaptive_learning
Revises: d2_agent_memories
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e3_adaptive_learning"
down_revision: Union[str, None] = "d2_agent_memories"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table("adaptive_plan_drafts",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("course_id", sa.Integer(), nullable=False),
        sa.Column("report_snapshot_id", sa.Integer(), nullable=True), sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"), sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True), sa.ForeignKeyConstraint(["course_id"], ["courses.id"]),
        sa.ForeignKeyConstraint(["report_snapshot_id"], ["learning_report_snapshots.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_adaptive_plan_drafts_course_id", "adaptive_plan_drafts", ["course_id"])
    op.create_index("ix_adaptive_plan_drafts_report_snapshot_id", "adaptive_plan_drafts", ["report_snapshot_id"])
    op.create_index("ix_adaptive_plan_drafts_status", "adaptive_plan_drafts", ["status"])
    op.create_table("adaptive_plan_draft_tasks",
        sa.Column("id", sa.Integer(), nullable=False), sa.Column("draft_id", sa.Integer(), nullable=False), sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("planned_date", sa.Date(), nullable=False), sa.Column("title", sa.String(160), nullable=False), sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("priority", sa.String(20), nullable=False), sa.Column("layer", sa.String(30), nullable=False), sa.Column("knowledge_point_id", sa.Integer(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False, server_default=""), sa.ForeignKeyConstraint(["draft_id"], ["adaptive_plan_drafts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["knowledge_point_id"], ["knowledge_points.id"]), sa.PrimaryKeyConstraint("id"))
    op.create_index("ix_adaptive_plan_draft_tasks_draft_id", "adaptive_plan_draft_tasks", ["draft_id"])


def downgrade() -> None:
    op.drop_index("ix_adaptive_plan_draft_tasks_draft_id", table_name="adaptive_plan_draft_tasks")
    op.drop_table("adaptive_plan_draft_tasks")
    for name in ("ix_adaptive_plan_drafts_status", "ix_adaptive_plan_drafts_report_snapshot_id", "ix_adaptive_plan_drafts_course_id"):
        op.drop_index(name, table_name="adaptive_plan_drafts")
    op.drop_table("adaptive_plan_drafts")
