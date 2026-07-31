from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import delete, select

from ai.ingestion.loaders import DocumentParserRegistry
from ai.ingestion.splitter import CitationAwareSplitter
from app.database import Database
from app.models import (
    DocumentChunk,
    DocumentIndex,
    ResourceFile,
)


INDEX_STATUS_LABELS = {
    "not_indexed": "未解析",
    "pending": "等待中",
    "parsing": "解析中",
    "parsed": "待向量化",
    "embedding": "向量化中",
    "completed": "索引完成",
    "failed": "解析失败",
    "stale": "需重建",
}


@dataclass(frozen=True, slots=True)
class IngestionResult:
    document_index_id: int
    resource_id: int
    chunk_count: int
    status: str
    reused: bool


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


class DocumentIngestionPipeline:
    """解析资料、切片并写入可追溯的数据库记录。"""

    def __init__(
        self,
        *,
        database: Database,
        workspace_dir: Path,
        parser_registry: DocumentParserRegistry,
        splitter: CitationAwareSplitter,
        embedding_model: str,
    ) -> None:
        self.database = database
        self.workspace_dir = workspace_dir.resolve()
        self.parser_registry = parser_registry
        self.splitter = splitter
        self.embedding_model = embedding_model

    def ingest(
        self,
        resource_id: int,
        *,
        force: bool = False,
    ) -> IngestionResult:
        resource = self._get_resource(resource_id)
        source_path = self._safe_resource_path(resource.relative_path)
        source_sha256 = file_sha256(source_path)

        existing = self._find_existing_index(
            resource_id=resource.id,
            parser_version="document-parser-v1",
            source_sha256=source_sha256,
        )

        if (
            existing is not None
            and existing.status in {"parsed", "completed"}
            and not force
        ):
            return IngestionResult(
                document_index_id=existing.id,
                resource_id=resource.id,
                chunk_count=existing.chunk_count,
                status=existing.status,
                reused=True,
            )

        index_id = self._prepare_index(
            resource=resource,
            source_sha256=source_sha256,
            existing=existing,
        )

        try:
            parsed = self.parser_registry.parse(source_path)
            chunks = self.splitter.split_document(parsed)

            if not chunks:
                raise ValueError("文档解析成功，但没有生成有效切片")

            self._store_chunks(
                document_index_id=index_id,
                resource=resource,
                chunks=chunks,
            )
        except Exception as exc:
            self._mark_failed(index_id, str(exc))
            raise

        return IngestionResult(
            document_index_id=index_id,
            resource_id=resource.id,
            chunk_count=len(chunks),
            status="parsed",
            reused=False,
        )

    def _get_resource(self, resource_id: int) -> ResourceFile:
        with self.database.session() as session:
            resource = session.get(ResourceFile, resource_id)

            if resource is None:
                raise ValueError("资料不存在")

            if resource.trashed:
                raise ValueError("回收站中的资料不能建立索引")

            # 会话结束后仍需使用这些字段，因此复制为独立对象。
            return ResourceFile(
                id=resource.id,
                name=resource.name,
                original_name=resource.original_name,
                source_path=resource.source_path,
                relative_path=resource.relative_path,
                sha256=resource.sha256,
                size=resource.size,
                course_id=resource.course_id,
                tags=resource.tags,
                trashed=resource.trashed,
                created_at=resource.created_at,
            )

    def _safe_resource_path(self, relative_path: str) -> Path:
        relative = Path(relative_path)

        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("资料路径越界")

        resolved = (self.workspace_dir / relative).resolve()

        if (
            resolved != self.workspace_dir
            and self.workspace_dir not in resolved.parents
        ):
            raise ValueError("资料路径越界")

        if not resolved.is_file():
            raise ValueError("资料文件不存在")

        return resolved

    def _find_existing_index(
        self,
        *,
        resource_id: int,
        parser_version: str,
        source_sha256: str,
    ) -> DocumentIndex | None:
        with self.database.session() as session:
            statement = select(DocumentIndex).where(
                DocumentIndex.resource_id == resource_id,
                DocumentIndex.parser_version == parser_version,
                DocumentIndex.chunker_version == self.splitter.version,
                DocumentIndex.embedding_model == self.embedding_model,
                DocumentIndex.source_sha256 == source_sha256,
            )

            item = session.scalar(statement)

            if item is None:
                return None

            return DocumentIndex(
                id=item.id,
                resource_id=item.resource_id,
                status=item.status,
                parser_version=item.parser_version,
                chunker_version=item.chunker_version,
                embedding_model=item.embedding_model,
                source_sha256=item.source_sha256,
                chunk_count=item.chunk_count,
                error_message=item.error_message,
                created_at=item.created_at,
                updated_at=item.updated_at,
                completed_at=item.completed_at,
            )

    def _prepare_index(
        self,
        *,
        resource: ResourceFile,
        source_sha256: str,
        existing: DocumentIndex | None,
    ) -> int:
        with self.database.session() as session:
            # 旧内容或旧配置产生的索引不删除，标记为 stale，
            # 后续向量索引清理时仍可追踪。
            old_indexes = list(
                session.scalars(
                    select(DocumentIndex).where(
                        DocumentIndex.resource_id == resource.id,
                        DocumentIndex.status == "completed",
                        DocumentIndex.source_sha256 != source_sha256,
                    )
                )
            )

            for old_index in old_indexes:
                old_index.status = "stale"
                old_index.updated_at = datetime.now()

            if existing is None:
                index = DocumentIndex(
                    resource_id=resource.id,
                    status="parsing",
                    parser_version="document-parser-v1",
                    chunker_version=self.splitter.version,
                    embedding_model=self.embedding_model,
                    source_sha256=source_sha256,
                    chunk_count=0,
                    error_message="",
                )
                session.add(index)
                session.flush()
                return index.id

            index = session.get(DocumentIndex, existing.id)
            if index is None:
                raise RuntimeError("文档索引记录不存在")

            session.execute(
                delete(DocumentChunk).where(
                    DocumentChunk.document_index_id == index.id
                )
            )

            index.status = "parsing"
            index.chunk_count = 0
            index.error_message = ""
            index.completed_at = None
            index.updated_at = datetime.now()

            return index.id

    def _store_chunks(
        self,
        *,
        document_index_id: int,
        resource: ResourceFile,
        chunks: list,
    ) -> None:
        with self.database.session() as session:
            index = session.get(DocumentIndex, document_index_id)

            if index is None:
                raise RuntimeError("文档索引记录不存在")

            for chunk in chunks:
                metadata_json = json.dumps(
                    {
                        **chunk.metadata,
                        "source_name": chunk.source_name,
                        "file_type": chunk.file_type,
                        "retrieval_text": chunk.retrieval_text,
                    },
                    ensure_ascii=False,
                    default=str,
                )

                session.add(
                    DocumentChunk(
                        document_index_id=document_index_id,
                        resource_id=resource.id,
                        course_id=resource.course_id,
                        chunk_number=chunk.chunk_number,
                        content=chunk.content,
                        content_sha256=chunk.content_sha256,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        line_start=chunk.line_start,
                        line_end=chunk.line_end,
                        section_title=chunk.section_title,
                        location_label=chunk.location_label,
                        metadata_json=metadata_json,
                        vector_id=None,
                        token_count=0,
                    )
                )

            index.status = "parsed"
            index.chunk_count = len(chunks)
            index.error_message = ""
            index.updated_at = datetime.now()
            index.completed_at = None

    def current_index_id(self, resource_id: int) -> int | None:
        with self.database.session() as session:
            item = session.scalar(
                select(DocumentIndex)
                .where(DocumentIndex.resource_id == resource_id)
                .order_by(DocumentIndex.updated_at.desc())
                .limit(1)
            )
        return item.id if item else None

    def _mark_failed(
        self,
        document_index_id: int,
        error_message: str,
    ) -> None:
        with self.database.session() as session:
            index = session.get(DocumentIndex, document_index_id)

            if index is None:
                return

            index.status = "failed"
            index.error_message = error_message[:4000]
            index.updated_at = datetime.now()
            index.completed_at = None
