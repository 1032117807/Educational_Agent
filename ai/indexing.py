from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ai.ingestion import DocumentIngestionPipeline
from ai.retrieval import ChromaVectorIndex
from ai.retrieval import SQLiteKeywordIndex


@dataclass(frozen=True, slots=True)
class FullIndexResult:
    document_index_id: int
    resource_id: int
    chunk_count: int
    vector_count: int
    reused: bool
    status: str = "completed"


class ResourceIndexingPipeline:
    """组合解析、切片和向量化。"""

    def __init__(
        self,
        *,
        ingestion: DocumentIngestionPipeline,
        vectors: ChromaVectorIndex,
        keywords: SQLiteKeywordIndex,
    ) -> None:
        self.ingestion = ingestion
        self.vectors = vectors
        self.keywords = keywords

    def index_resource(
        self,
        resource_id: int,
        *,
        force: bool = False,
        progress: Callable[[int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> FullIndexResult:
        if force:
            current_index_id = self.ingestion.current_index_id(resource_id)
            if current_index_id is not None:
                self.vectors.delete_document_vectors(current_index_id)
                self.keywords.delete_document(current_index_id)

        if should_cancel and should_cancel():
            raise InterruptedError("用户取消了索引任务")

        if progress:
            progress(5)

        ingestion_result = self.ingestion.ingest(
            resource_id,
            force=force,
        )

        if progress:
            progress(35)

        self.keywords.rebuild_document(
            ingestion_result.document_index_id
        )

        if progress:
            progress(45)

        vector_result = self.vectors.index_document(
            ingestion_result.document_index_id,
            progress=(
                lambda value: progress(45 + int(value * 0.55))
                if progress
                else None
            ),
            should_cancel=should_cancel,
        )

        if progress:
            progress(100)

        return FullIndexResult(
            document_index_id=ingestion_result.document_index_id,
            resource_id=resource_id,
            chunk_count=ingestion_result.chunk_count,
            vector_count=vector_result.total_count,
            reused=(
                ingestion_result.reused
                and vector_result.reused
            ),
        )
