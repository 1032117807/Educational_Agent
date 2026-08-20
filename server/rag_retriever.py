from __future__ import annotations

import json
import logging
from collections.abc import Sequence
from dataclasses import replace

from langchain_core.embeddings import Embeddings
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.orm import Session

from ai.retrieval.hybrid import RetrievalHit
from ai.retrieval.query_planner import RetrievalQueryPlanner
from ai.gateways.rerank import Reranker
from app.models import DocumentChunk, DocumentIndex, ResourceFile
from server.pgvector_store import PgVectorStore

logger = logging.getLogger(__name__)


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
        reranker: Reranker | None = None,
        rerank_candidate_limit: int = 24,
        query_rewrite_enabled: bool = True,
        hybrid_retrieval_enabled: bool = True,
    ) -> None:
        self.session = session
        self.embeddings = embeddings
        self.embedding_version = embedding_version
        self.vectors = PgVectorStore(session, dimensions=dimensions)
        self.reranker = reranker
        self.rerank_candidate_limit = rerank_candidate_limit
        self.query_rewrite_enabled = query_rewrite_enabled
        self.hybrid_retrieval_enabled = hybrid_retrieval_enabled
        self.query_planner = RetrievalQueryPlanner()

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
        if self.query_rewrite_enabled:
            query = self.query_planner.plan(query, course_id=course_id).primary_query
        vector_hits = self.vectors.search(
            tenant_id=tenant_id,
            embedding_version=self.embedding_version,
            query_embedding=self.embeddings.embed_query(query),
            limit=max(limit * 3, limit, self.rerank_candidate_limit if self.reranker else limit),
            course_id=course_id,
            resource_ids=resource_ids,
        )
        keyword_hits = (
            self._keyword_hits(query, tenant_id=tenant_id, limit=max(limit * 3, limit))
            if self.hybrid_retrieval_enabled else []
        )
        if not vector_hits and not keyword_hits:
            return []
        vector_rank = {hit.chunk_id: rank for rank, hit in enumerate(vector_hits, start=1)}
        keyword_rank = {chunk_id: rank for rank, chunk_id in enumerate(keyword_hits, start=1)}
        scores: dict[int, float] = {}
        for chunk_id, rank in vector_rank.items(): scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (60 + rank)
        for chunk_id, rank in keyword_rank.items(): scores[chunk_id] = scores.get(chunk_id, 0.0) + 1 / (60 + rank)
        ids = sorted(scores, key=lambda chunk_id: (-scores[chunk_id], chunk_id))[:max(limit * 3, limit)]
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
                rrf_score=scores[chunk_id],
                keyword_rank=keyword_rank.get(chunk_id),
                semantic_rank=vector_rank.get(chunk_id),
                keyword_score=None,
                semantic_distance=distance_by_id.get(chunk_id),
                metadata=metadata,
            ))
        if self.reranker and output:
            try:
                candidates = output[:self.rerank_candidate_limit]
                rerank_scores = self.reranker.rerank(
                    query,
                    [hit.retrieval_text or hit.content for hit in candidates],
                    limit=len(candidates),
                )
                if len(rerank_scores) != len(candidates):
                    raise ValueError("reranker returned an unexpected score count")
                score_by_chunk = {
                    hit.chunk_id: rerank_scores[index]
                    for index, hit in enumerate(candidates)
                }
                output = [
                    item[1] for item in sorted(
                        enumerate(candidates), key=lambda item: (-rerank_scores[item[0]], item[0])
                    )
                ] + output[len(candidates):]
                return [
                    replace(
                        hit, rerank_score=score_by_chunk.get(hit.chunk_id),
                        final_rank=index + 1, retrieval_stage="rerank",
                    )
                    for index, hit in enumerate(output[:limit])
                ]
            except Exception:
                # Retrieval must remain available when a paid rerank service times out.
                logger.exception("Rerank failed; using pgvector order")
        return [replace(hit, final_rank=index + 1, retrieval_stage="rrf") for index, hit in enumerate(output[:limit])]

    def _keyword_hits(self, query: str, *, tenant_id: str, limit: int) -> list[int]:
        """PostgreSQL FTS candidate path, tenant-scoped before RRF merging."""
        try:
            rows = self.session.execute(text("""
                SELECT id
                FROM document_chunks
                WHERE tenant_id = :tenant_id
                  AND to_tsvector('simple', content) @@ plainto_tsquery('simple', :query)
                ORDER BY ts_rank(to_tsvector('simple', content), plainto_tsquery('simple', :query)) DESC, id
                LIMIT :limit
            """), {"tenant_id": tenant_id, "query": query, "limit": limit})
            return [int(row.id) for row in rows]
        except Exception:
            # RLS/pgvector retrieval remains available if FTS is not installed
            # or the deployment has not yet created an expression index.
            logger.exception("PostgreSQL FTS failed; using vector candidates")
            return []
