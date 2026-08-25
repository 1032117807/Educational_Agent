"""bind learner material and practice sessions to study tasks

Revision ID: g17_task_assignments
Revises: g16_course_notes
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "g17_task_assignments"
down_revision: Union[str, None] = "g16_course_notes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("study_tasks.id"), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), sa.ForeignKey("knowledge_points.id"), nullable=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=True),
        sa.Column("review_item_id", sa.Integer(), sa.ForeignKey("review_items.id"), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    for column in ("tenant_id", "task_id", "knowledge_point_id", "question_id", "review_item_id"):
        op.create_index(f"ix_task_assignments_{column}", "task_assignments", [column])
    with op.batch_alter_table("practice_sessions") as batch:
        batch.add_column(sa.Column("task_id", sa.Integer(), sa.ForeignKey("study_tasks.id"), nullable=True))
        batch.create_index("ix_practice_sessions_task_id", ["task_id"], unique=False)
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE task_assignments ENABLE ROW LEVEL SECURITY")
        op.execute("CREATE POLICY tenant_isolation_task_assignments ON task_assignments USING (tenant_id = current_setting('app.tenant_id', true)) WITH CHECK (tenant_id = current_setting('app.tenant_id', true))")


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation_task_assignments ON task_assignments")
        op.execute("ALTER TABLE task_assignments DISABLE ROW LEVEL SECURITY")
    with op.batch_alter_table("practice_sessions") as batch:
        batch.drop_index("ix_practice_sessions_task_id")
        batch.drop_column("task_id")
    for column in ("review_item_id", "question_id", "knowledge_point_id", "task_id", "tenant_id"):
        op.drop_index(f"ix_task_assignments_{column}", table_name="task_assignments")
    op.drop_table("task_assignments")
