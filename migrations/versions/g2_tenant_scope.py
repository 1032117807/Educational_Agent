"""add tenant scope to core learning and RAG records"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = "g2_tenant_scope"
down_revision: Union[str, None] = "g1_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None
TABLES = ("courses", "resource_files", "document_indexes", "document_chunks", "ai_runs", "background_jobs")

def upgrade() -> None:
    for table in TABLES:
        op.add_column(table, sa.Column("tenant_id", sa.String(length=36), nullable=True))
        op.create_index(f"ix_{table}_tenant_id", table, ["tenant_id"])
    op.add_column("background_jobs", sa.Column("requested_by", sa.String(length=36), nullable=True))
    op.create_index("ix_background_jobs_requested_by", "background_jobs", ["requested_by"])

def downgrade() -> None:
    op.drop_index("ix_background_jobs_requested_by", table_name="background_jobs")
    op.drop_column("background_jobs", "requested_by")
    for table in reversed(TABLES):
        op.drop_index(f"ix_{table}_tenant_id", table_name=table)
        op.drop_column(table, "tenant_id")
