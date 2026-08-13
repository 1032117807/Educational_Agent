"""add tenant-scoped pgvector document embeddings"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g3_pgvector_embeddings"
down_revision: Union[str, None] = "g2_tenant_scope"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE document_embeddings (
            id BIGSERIAL PRIMARY KEY,
            tenant_id VARCHAR(36) NOT NULL,
            chunk_id BIGINT NOT NULL REFERENCES document_chunks(id) ON DELETE CASCADE,
            embedding_model VARCHAR(160) NOT NULL,
            embedding_version VARCHAR(80) NOT NULL,
            content_sha256 VARCHAR(64) NOT NULL,
            embedding vector(384) NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (chunk_id, embedding_version)
        )
        """
    )
    op.execute("CREATE INDEX ix_document_embeddings_tenant_model ON document_embeddings (tenant_id, embedding_version)")
    op.execute("CREATE INDEX ix_document_embeddings_chunk ON document_embeddings (chunk_id)")
    op.execute(
        "CREATE INDEX ix_document_embeddings_hnsw ON document_embeddings "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TABLE IF EXISTS document_embeddings")
