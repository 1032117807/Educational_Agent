from __future__ import annotations

import json
from collections.abc import Sequence

from langchain_core.embeddings import Embeddings
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai.retrieval.hybrid import RetrievalHit
from app.models import DocumentChunk, DocumentIndex, ResourceFile
from server.pgvector_store import PgVectorStore


class TenantPgVectorRetriever:
    """RAG semantic retriever for the SaaS backend.

    The tenant predicate is enforced by both pgvector and the relational chunk
    lookup so stale vectors cannot cross a tenant boundary.
    """

    def __init__(
        self,
        *,
        session: Session,
        embeddings: Embeddings,
        embedding_version: str,
        dimensions: int,
    ) -> None:
        self.session = session
        self.embeddings = embeddings
        self.embedding_version = embedding_version
        self.vectors = PgVectorStore(session, dimensions=dimensions)

    def retrieve(
        self,
        query: str,
        *,
        tenant_id: str,
        limit: int = 8,
        course_id: int | None = None,
        resource_ids: Sequence[int] | None = None,
    ) -> list[RetrievalHit]:
        if not query.strip():
            return []
        vector_hits = self.vectors.search(
            tenant_id=tenant_id,
            embedding_version=self.embedding_version,
            query_embedding=self.embeddings.embed_query(query),
            limit=max(limit * 3, limit),
        )
        if not vector_hits:
            return []
        ids = [hit.chunk_id for hit in vector_hits]
        statement = (
            select(DocumentChunk)
            .join(DocumentIndex, DocumentIndex.id == DocumentChunk.document_index_id)
            .join(ResourceFile, ResourceFile.id == DocumentChunk.resource_id)
            .where(
                DocumentChunk.id.in_(ids),
                DocumentChunk.tenant_id == tenant_id,
                DocumentIndex.tenant_id == tenant_id,
                ResourceFile.tenant_id == tenant_id,
                DocumentIndex.status == "completed",
                ResourceFile.trashed.is_(False),
            )
        )
        if course_id is not None:
            statement = statement.where(DocumentChunk.course_id == course_id)
        if resource_ids:
            statement = statement.where(DocumentChunk.resource_id.in_(resource_ids))
        chunks = {item.id: item for item in self.session.scalars(statement)}
        distance_by_id = {item.chunk_id: item.distance for item in vector_hits}
        output: list[RetrievalHit] = []
        for rank, chunk_id in enumerate(ids, start=1):
            chunk = chunks.get(chunk_id)
            if chunk is None:
                continue
            metadata = json.loads(chunk.metadata_json or "{}")
            output.append(RetrievalHit(
                chunk_id=chunk.id,
                resource_id=chunk.resource_id,
                document_index_id=chunk.document_index_id,
                source_name=str(metadata.get("source_name", "")),
                content=chunk.content,
                retrieval_text=str(metadata.get("retrieval_text", chunk.content)),
                location_label=chunk.location_label,
                section_title=chunk.section_title,
                page_start=chunk.page_start,
                page_end=chunk.page_end,
                line_start=chunk.line_start,
                line_end=chunk.line_end,
                rrf_score=1 / (60 + rank),
                keyword_rank=None,
                semantic_rank=rank,
                keyword_score=None,
                semantic_distance=distance_by_id[chunk_id],
                metadata=metadata,
            ))
            if len(output) >= limit:
                break
        return output
