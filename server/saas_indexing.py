from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ai.ingestion import DocumentIngestionPipeline
from server.pgvector_indexer import PgVectorDocumentIndexer


@dataclass(frozen=True, slots=True)
class SaaSIndexResult:
    document_index_id: int
    resource_id: int
    chunk_count: int
    vector_count: int


class SaaSResourceIndexingPipeline:
    """Object-store worker pipeline: parse/chunk then write pgvector, never Chroma."""

    def __init__(self, *, ingestion: DocumentIngestionPipeline, vectors: PgVectorDocumentIndexer) -> None:
        self.ingestion = ingestion
        self.vectors = vectors

    def index_resource(self, resource_id: int, *, source_path_override: Path, force: bool = False) -> SaaSIndexResult:
        ingested = self.ingestion.ingest(resource_id, force=force, source_path_override=source_path_override)
        vector_result = self.vectors.index_document(ingested.document_index_id)
        return SaaSIndexResult(
            document_index_id=ingested.document_index_id,
            resource_id=resource_id,
            chunk_count=ingested.chunk_count,
            vector_count=vector_result.indexed_count,
        )
