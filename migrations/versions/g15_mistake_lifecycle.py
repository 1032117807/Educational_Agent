"""add mistake provenance and review lifecycle fields

Revision ID: g15_mistake_lifecycle
Revises: g14_task_lifecycle
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g15_mistake_lifecycle"
down_revision: Union[str, None] = "g14_task_lifecycle"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("review_items") as batch:
        batch.add_column(sa.Column("ai_analysis", sa.Text(), nullable=False, server_default=""))
        batch.add_column(sa.Column("created_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("last_reviewed_at", sa.DateTime(), nullable=True))
        batch.create_index("ix_review_items_created_at", ["created_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("review_items") as batch:
        batch.drop_index("ix_review_items_created_at")
        batch.drop_column("last_reviewed_at")
        batch.drop_column("created_at")
        batch.drop_column("ai_analysis")
