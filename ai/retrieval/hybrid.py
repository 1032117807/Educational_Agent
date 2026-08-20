from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace

from sqlalchemy import select

from ai.retrieval.keyword_store import (
    KeywordHit,
    SQLiteKeywordIndex,
)
from ai.retrieval.vector_store import (
    ChromaVectorIndex,
    SemanticHit,
)
from app.database import Database
from app.models import DocumentChunk, DocumentIndex, ResourceFile
from ai.gateways.rerank import Reranker

logger = logging.getLogger(__name__)

@dataclass(frozen=True, slots=True)
class RetrievalHit:
    chunk_id: int
    resource_id: int
    document_index_id: int
    source_name: str
    content: str
    retrieval_text: str
    location_label: str
    section_title: str

    page_start: int | None
    page_end: int | None
    line_start: int | None
    line_end: int | None

    rrf_score: float
    keyword_rank: int | None
    semantic_rank: int | None
    keyword_score: float | None
    semantic_distance: float | None

    metadata: dict[str, object] = field(default_factory=dict)
    rerank_score: float | None = None
    final_rank: int | None = None
    retrieval_stage: str = "rrf"

    @property
    def citation_label(self) -> str:
        if self.location_label:
            return f"{self.source_name}，{self.location_label}"

        return self.source_name


class HybridRetriever:
    def __init__(
        self,
        *,
        database: Database,
        keyword_index: SQLiteKeywordIndex,
        vector_index: ChromaVectorIndex,
        rrf_k: int = 60,
        keyword_weight: float = 1.0,
        semantic_weight: float = 1.0,
        reranker: Reranker | None = None,
        rerank_candidate_limit: int = 24,
    ) -> None:
        if rrf_k <= 0:
            raise ValueError("rrf_k 必须大于 0")

        self.database = database
        self.keyword_index = keyword_index
        self.vector_index = vector_index
        self.rrf_k = rrf_k
        self.keyword_weight = keyword_weight
        self.semantic_weight = semantic_weight
        self.reranker = reranker
        self.rerank_candidate_limit = rerank_candidate_limit

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 8,
        candidate_limit: int = 30,
        course_id: int | None = None,
        resource_ids: list[int] | None = None,
    ) -> list[RetrievalHit]:
        if not query.strip():
            return []

        keyword_hits = self.keyword_index.search(
            query,
            limit=candidate_limit,
            course_id=course_id,
            resource_ids=resource_ids,
        )

        try:
            semantic_hits = self.vector_index.search(
                query,
                limit=candidate_limit,
                course_id=course_id,
                resource_ids=resource_ids,
            )
        except Exception:
            logger.warning(
                "语义检索不可用，已降级为关键词检索",
                exc_info=True,
            )
            semantic_hits = []

        scores: dict[int, float] = {}
        keyword_by_id: dict[int, KeywordHit] = {}
        semantic_by_id: dict[int, SemanticHit] = {}

        for hit in keyword_hits:
            keyword_by_id[hit.chunk_id] = hit
            scores[hit.chunk_id] = (
                scores.get(hit.chunk_id, 0.0)
                + self.keyword_weight
                / (self.rrf_k + hit.rank)
            )

        for hit in semantic_hits:
            semantic_by_id[hit.chunk_id] = hit
            scores[hit.chunk_id] = (
                scores.get(hit.chunk_id, 0.0)
                + self.semantic_weight
                / (self.rrf_k + hit.rank)
            )

        ranked_ids = sorted(
            scores,
            key=lambda chunk_id: (
                -scores[chunk_id],
                chunk_id,
            ),
        )[:max(limit, self.rerank_candidate_limit if self.reranker else limit)]

        chunks = self._load_chunks(ranked_ids)
        chunk_by_id = {chunk.id: chunk for chunk in chunks}

        results: list[RetrievalHit] = []

        for chunk_id in ranked_ids:
            chunk = chunk_by_id.get(chunk_id)
            if chunk is None:
                continue

            metadata = json.loads(chunk.metadata_json or "{}")
            keyword_hit = keyword_by_id.get(chunk_id)
            semantic_hit = semantic_by_id.get(chunk_id)

            results.append(
                RetrievalHit(
                    chunk_id=chunk.id,
                    resource_id=chunk.resource_id,
                    document_index_id=chunk.document_index_id,
                    source_name=str(
                        metadata.get("source_name", "")
                    ),
                    content=chunk.content,
                    retrieval_text=str(
                        metadata.get(
                            "retrieval_text",
                            chunk.content,
                        )
                    ),
                    location_label=chunk.location_label,
                    section_title=chunk.section_title,
                    page_start=chunk.page_start,
                    page_end=chunk.page_end,
                    line_start=chunk.line_start,
                    line_end=chunk.line_end,
                    rrf_score=scores[chunk_id],
                    keyword_rank=(
                        keyword_hit.rank
                        if keyword_hit
                        else None
                    ),
                    semantic_rank=(
                        semantic_hit.rank
                        if semantic_hit
                        else None
                    ),
                    keyword_score=(
                        keyword_hit.bm25_score
                        if keyword_hit
                        else None
                    ),
                    semantic_distance=(
                        semantic_hit.distance
                        if semantic_hit
                        else None
                    ),
                    metadata=metadata,
                )
            )

        if self.reranker and results:
            try:
                candidates = results[:self.rerank_candidate_limit]
                rerank_scores = self.reranker.rerank(
                    query,
                    [hit.retrieval_text or hit.content for hit in candidates],
                    limit=len(candidates),
                )
                score_by_chunk = {
                    hit.chunk_id: rerank_scores[index]
                    for index, hit in enumerate(candidates)
                }
                results = [
                    item[1]
                    for item in sorted(
                        enumerate(candidates),
                        key=lambda item: (-rerank_scores[item[0]], item[0]),
                    )
                ] + results[len(candidates):]
                results = [
                    replace(
                        hit,
                        rerank_score=score_by_chunk.get(hit.chunk_id),
                        final_rank=index + 1,
                        retrieval_stage="rerank",
                    )
                    for index, hit in enumerate(results[:limit])
                ]
            except Exception:
                logger.exception("Rerank failed; using RRF order")
                results = [replace(hit, final_rank=index + 1) for index, hit in enumerate(results[:limit])]
        else:
            results = [replace(hit, final_rank=index + 1) for index, hit in enumerate(results[:limit])]
        return results


    def _load_chunks(
        self,
        chunk_ids: list[int],
    ) -> list[DocumentChunk]:
        if not chunk_ids:
            return []

        with self.database.session() as session:
            chunks = list(
                session.scalars(
                    select(DocumentChunk)
                    .join(
                        DocumentIndex,
                        DocumentIndex.id
                        == DocumentChunk.document_index_id,
                    )
                    .join(
                        ResourceFile,
                        ResourceFile.id
                        == DocumentChunk.resource_id,
                    )
                    .where(
                        DocumentChunk.id.in_(chunk_ids),
                        DocumentIndex.status == "completed",
                        ResourceFile.trashed.is_(False),
                    )
                )
            )

            return [
                DocumentChunk(
                    id=item.id,
                    document_index_id=item.document_index_id,
                    resource_id=item.resource_id,
                    course_id=item.course_id,
                    chunk_number=item.chunk_number,
                    content=item.content,
                    content_sha256=item.content_sha256,
                    page_start=item.page_start,
                    page_end=item.page_end,
                    line_start=item.line_start,
                    line_end=item.line_end,
                    section_title=item.section_title,
                    location_label=item.location_label,
                    metadata_json=item.metadata_json,
                    vector_id=item.vector_id,
                    token_count=item.token_count,
                    created_at=item.created_at,
                )
                for item in chunks
            ]
