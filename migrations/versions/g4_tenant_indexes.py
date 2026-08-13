"""add composite indexes for tenant-scoped SaaS queries"""
from typing import Sequence, Union
from alembic import op

revision: str = "g4_tenant_indexes"
down_revision: Union[str, None] = "g3_pgvector_embeddings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.create_index("ix_courses_tenant_status_id", "courses", ["tenant_id", "status", "id"])
    op.create_index("ix_resources_tenant_sha256", "resource_files", ["tenant_id", "sha256"])
    op.create_index("ix_document_indexes_tenant_status", "document_indexes", ["tenant_id", "status", "updated_at"])
    op.create_index("ix_document_chunks_tenant_resource", "document_chunks", ["tenant_id", "resource_id", "id"])
    op.create_index("ix_background_jobs_tenant_status", "background_jobs", ["tenant_id", "status", "created_at"])

def downgrade() -> None:
    op.drop_index("ix_background_jobs_tenant_status", table_name="background_jobs")
    op.drop_index("ix_document_chunks_tenant_resource", table_name="document_chunks")
    op.drop_index("ix_document_indexes_tenant_status", table_name="document_indexes")
    op.drop_index("ix_resources_tenant_sha256", table_name="resource_files")
    op.drop_index("ix_courses_tenant_status_id", table_name="courses")
