"""add course-scoped learning notes

Revision ID: g16_course_notes
Revises: g15_mistake_lifecycle
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g16_course_notes"
down_revision: Union[str, None] = "g15_mistake_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "course_notes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("course_id", sa.Integer(), sa.ForeignKey("courses.id"), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False, server_default="学习笔记"),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_course_notes_tenant_id", "course_notes", ["tenant_id"])
    op.create_index("ix_course_notes_course_id", "course_notes", ["course_id"])
    op.create_index("ix_course_notes_created_at", "course_notes", ["created_at"])
    if op.get_bind().dialect.name == "postgresql":
        op.execute("ALTER TABLE course_notes ENABLE ROW LEVEL SECURITY")
        op.execute(
            "CREATE POLICY tenant_isolation_course_notes ON course_notes "
            "USING (tenant_id = current_setting('app.tenant_id', true)) "
            "WITH CHECK (tenant_id = current_setting('app.tenant_id', true))"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute("DROP POLICY IF EXISTS tenant_isolation_course_notes ON course_notes")
        op.execute("ALTER TABLE course_notes DISABLE ROW LEVEL SECURITY")
    op.drop_index("ix_course_notes_created_at", table_name="course_notes")
    op.drop_index("ix_course_notes_course_id", table_name="course_notes")
    op.drop_index("ix_course_notes_tenant_id", table_name="course_notes")
    op.drop_table("course_notes")
