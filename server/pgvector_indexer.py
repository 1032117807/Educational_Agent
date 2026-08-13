from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass

from langchain_core.embeddings import Embeddings
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import DocumentChunk, DocumentIndex
from server.pgvector_store import PgVectorStore
from server.tenant_session import set_session_tenant


def embedding_version_for(model_name: str, dimensions: int) -> str:
    digest = hashlib.sha256(f"{model_name}:{dimensions}".encode()).hexdigest()[:12]
    return f"{model_name[:60]}-{dimensions}-{digest}"


@dataclass(frozen=True, slots=True)
class PgVectorIndexResult:
    document_index_id: int
    indexed_count: int
    reused: bool


class PgVectorDocumentIndexer:
    """Embed parsed chunks and write them to tenant-scoped pgvector storage."""

    def __init__(
        self,
        *,
        session_factory: Callable[[], Session],
        embeddings: Embeddings,
        embedding_model: str,
        dimensions: int,
        batch_size: int = 32,
        tenant_id: str | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.embeddings = embeddings
        self.embedding_model = embedding_model
        self.dimensions = dimensions
        self.batch_size = batch_size
        self.embedding_version = embedding_version_for(embedding_model, dimensions)
        self.tenant_id = tenant_id

    def index_document(self, document_index_id: int) -> PgVectorIndexResult:
        with self.session_factory() as session:
            # Read the index only under its tenant RLS context.
            if self.tenant_id:
                set_session_tenant(session, self.tenant_id)
            index = session.get(DocumentIndex, document_index_id)
            if index is None:
                raise ValueError("document index not found")
            if not index.tenant_id:
                raise ValueError("document index has no tenant")
            if not self.tenant_id:
                set_session_tenant(session, index.tenant_id)
            chunks = list(session.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_index_id == document_index_id, DocumentChunk.tenant_id == index.tenant_id)
                .order_by(DocumentChunk.chunk_number)
            ))
            if not chunks:
                raise ValueError("document index has no chunks")
            tenant_id = index.tenant_id
            index.status = "embedding"
            session.commit()

        indexed = 0
        try:
            for offset in range(0, len(chunks), self.batch_size):
                batch = chunks[offset: offset + self.batch_size]
                vectors = self.embeddings.embed_documents([chunk.content for chunk in batch])
                if len(vectors) != len(batch):
                    raise RuntimeError("embedding provider returned an unexpected vector count")
                with self.session_factory() as session:
                    set_session_tenant(session, tenant_id)
                    store = PgVectorStore(session, dimensions=self.dimensions)
                    for chunk, vector in zip(batch, vectors, strict=True):
                        store.upsert(
                            tenant_id=tenant_id,
                            chunk_id=chunk.id,
                            embedding_model=self.embedding_model,
                            embedding_version=self.embedding_version,
                            content_sha256=chunk.content_sha256,
                            embedding=vector,
                        )
                    session.commit()
                indexed += len(batch)
        except Exception as exc:
            with self.session_factory() as session:
                set_session_tenant(session, tenant_id)
                index = session.get(DocumentIndex, document_index_id)
                if index is not None:
                    index.status = "failed"
                    index.error_message = f"pgvector embedding failed: {exc}"[:4000]
                    session.commit()
            raise

        with self.session_factory() as session:
            set_session_tenant(session, tenant_id)
            index = session.get(DocumentIndex, document_index_id)
            if index is None:
                raise RuntimeError("document index disappeared during embedding")
            index.status = "completed"
            index.error_message = ""
            session.commit()
        return PgVectorIndexResult(document_index_id=document_index_id, indexed_count=indexed, reused=False)
