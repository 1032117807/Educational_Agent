"""add explicit study task lifecycle fields

Revision ID: g14_task_lifecycle
Revises: g13_task_knowledge_links
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g14_task_lifecycle"
down_revision: Union[str, None] = "g13_task_knowledge_links"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("study_tasks") as batch:
        batch.add_column(sa.Column("status", sa.String(length=20), nullable=False, server_default="planned"))
        batch.add_column(sa.Column("started_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_study_tasks_status", ["status"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("study_tasks") as batch:
        batch.drop_index("ix_study_tasks_status")
        batch.drop_column("started_at")
        batch.drop_column("status")
