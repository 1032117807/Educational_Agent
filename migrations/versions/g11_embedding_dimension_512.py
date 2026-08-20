"""migrate BGE small Chinese embeddings to 512 dimensions

Revision ID: g11_embedding_dimension_512
Revises: g10_tenant_not_null
"""

from typing import Sequence, Union
import json

from alembic import op
import sqlalchemy as sa


revision: str = "g11_embedding_dimension_512"
down_revision: Union[str, None] = "g10_tenant_not_null"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    # Existing 384-d vectors cannot be cast to 512 dimensions. Drop only the
    # derived vectors, keep source chunks/resources, and require re-indexing.
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_hnsw")
    op.execute("DELETE FROM document_embeddings")
    op.execute("ALTER TABLE document_embeddings ALTER COLUMN embedding TYPE vector(512)")
    op.execute(
        "CREATE INDEX ix_document_embeddings_hnsw ON document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
    op.execute("UPDATE document_indexes SET status = 'pending', error_message = 're-index required after embedding dimension migration', completed_at = NULL")
    rows = bind.execute(sa.text("SELECT id, tenant_id FROM resource_files WHERE trashed = FALSE AND tenant_id IS NOT NULL")).fetchall()
    for resource_id, tenant_id in rows:
        exists = bind.execute(sa.text(
            "SELECT 1 FROM background_jobs WHERE tenant_id = :tenant_id AND job_type = 'index_resource' "
            "AND status IN ('queued', 'running') AND payload LIKE :needle LIMIT 1"),
            {"tenant_id": tenant_id, "needle": f'%\"resource_id\": {resource_id}%"%'},
        ).fetchone()
        if not exists:
            bind.execute(sa.text(
                "INSERT INTO background_jobs (tenant_id, job_type, status, payload, detail, progress, created_at) "
                "VALUES (:tenant_id, 'index_resource', 'queued', :payload, 're-index queued after embedding dimension migration', 0, CURRENT_TIMESTAMP)"),
                {"tenant_id": tenant_id, "payload": json.dumps({"tenant_id": tenant_id, "resource_id": resource_id})},
            )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP INDEX IF EXISTS ix_document_embeddings_hnsw")
    op.execute("DELETE FROM document_embeddings")
    op.execute("ALTER TABLE document_embeddings ALTER COLUMN embedding TYPE vector(384)")
    op.execute(
        "CREATE INDEX ix_document_embeddings_hnsw ON document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )
