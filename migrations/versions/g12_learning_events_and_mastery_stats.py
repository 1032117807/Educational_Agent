"""add structured mastery statistics and learning events

Revision ID: g12_learning_events_mastery
Revises: g11_embedding_dimension_512
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g12_learning_events_mastery"
down_revision: Union[str, None] = "g11_embedding_dimension_512"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("knowledge_points") as batch:
        batch.add_column(sa.Column("practice_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("correct_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("wrong_count", sa.Integer(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("last_studied_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("next_review_at", sa.DateTime(), nullable=True))

    op.create_table(
        "learning_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        # SaaS events are always tenant-scoped; desktop SQLite keeps the
        # model nullable for backwards compatibility with legacy local data.
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=True),
        sa.Column("event_type", sa.String(length=60), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("study_tasks.id"), nullable=True),
        sa.Column("question_id", sa.Integer(), sa.ForeignKey("questions.id"), nullable=True),
        sa.Column("knowledge_point_id", sa.Integer(), sa.ForeignKey("knowledge_points.id"), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("occurred_at", sa.DateTime(), nullable=False),
    )
    for column in ("tenant_id", "user_id", "event_type", "course_id", "task_id", "question_id", "knowledge_point_id", "occurred_at"):
        op.create_index(f"ix_learning_events_{column}", "learning_events", [column])
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("ALTER TABLE learning_events ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_isolation_learning_events ON learning_events "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation_learning_events ON learning_events")
        op.execute("ALTER TABLE learning_events DISABLE ROW LEVEL SECURITY")
    for column in ("tenant_id", "user_id", "event_type", "course_id", "task_id", "question_id", "knowledge_point_id", "occurred_at"):
        op.drop_index(f"ix_learning_events_{column}", table_name="learning_events")
    op.drop_table("learning_events")
    with op.batch_alter_table("knowledge_points") as batch:
        for column in ("next_review_at", "last_studied_at", "wrong_count", "correct_count", "practice_count"):
            batch.drop_column(column)
