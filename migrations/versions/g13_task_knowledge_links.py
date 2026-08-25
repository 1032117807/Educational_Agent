"""link study tasks to tenant-scoped knowledge points

Revision ID: g13_task_knowledge_links
Revises: g12_learning_events_mastery
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g13_task_knowledge_links"
down_revision: Union[str, None] = "g12_learning_events_mastery"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("study_tasks") as batch:
        batch.add_column(sa.Column("knowledge_point_id", sa.Integer(), nullable=True))
        batch.create_index("ix_study_tasks_knowledge_point_id", ["knowledge_point_id"], unique=False)
        batch.create_foreign_key("fk_study_tasks_knowledge_point_id", "knowledge_points", ["knowledge_point_id"], ["id"])


def downgrade() -> None:
    with op.batch_alter_table("study_tasks") as batch:
        batch.drop_constraint("fk_study_tasks_knowledge_point_id", type_="foreignkey")
        batch.drop_index("ix_study_tasks_knowledge_point_id")
        batch.drop_column("knowledge_point_id")
