"""scope association and attempt records to a tenant

Revision ID: g6_tenant_join_records
Revises: g5_remaining_tenant_scope
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g6_tenant_join_records"
down_revision: Union[str, None] = "g5_remaining_tenant_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# question_attempts was introduced in g5. The other records link tenant-owned
# entities and need their own scope to support future database RLS policies.
TABLES = ("practice_session_questions", "review_attempts", "task_recurrences")


def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(length=36), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
