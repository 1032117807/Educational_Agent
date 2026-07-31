from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from sqlalchemy import select

from app.database import Database
from app.models import DocumentChunk, DocumentIndex, ResourceFile


@dataclass(frozen=True, slots=True)
class SemanticHit:
    chunk_id: int
    rank: int
    distance: float


@dataclass(frozen=True, slots=True)
class VectorIndexResult:
    document_index_id: int
    indexed_count: int
    total_count: int
    reused: bool


def vector_id_for(
    *,
    document_index_id: int,
    chunk_number: int,
    content_sha256: str,
) -> str:
    """根据稳定业务属性生成可重复的向量 ID。"""

    return (
        f"index-{document_index_id}"
        f"-chunk-{chunk_number}"
        f"-{content_sha256[:16]}"
    )


def collection_name_for(prefix: str, model_name: str) -> str:
    """不同 Embedding 模型使用不同 Chroma collection。"""

    safe_model = re.sub(r"[^a-zA-Z0-9_-]+", "-", model_name).strip("-")
    digest = hashlib.sha256(model_name.encode("utf-8")).hexdigest()[:8]
    name = f"{prefix}-{safe_model}-{digest}"

    # Chroma collection 名称不宜过长。
    return name[:63].rstrip("-_")


class ChromaVectorIndex:
    def __init__(
        self,
        *,
        database: Database,
        embeddings: Embeddings,
        persist_directory: Path,
        embedding_model: str,
        collection_prefix: str = "learning_chunks",
        batch_size: int = 32,
        vector_store: Any | None = None,
    ) -> None:
        self.database = database
        self.embeddings = embeddings
        self.persist_directory = persist_directory.resolve()
        self.embedding_model = embedding_model
        self.batch_size = batch_size

        self.persist_directory.mkdir(parents=True, exist_ok=True)

        self.collection_name = collection_name_for(
            collection_prefix,
            embedding_model,
        )

        if vector_store is None:
            from langchain_chroma import Chroma

            vector_store = Chroma(
                collection_name=self.collection_name,
                embedding_function=embeddings,
                persist_directory=str(self.persist_directory),
                collection_metadata={
                    "hnsw:space": "cosine",
                    "embedding_model": embedding_model,
                },
            )
        self.vector_store = vector_store

    def index_document(
        self,
        document_index_id: int,
        *,
        progress: Callable[[int], None] | None = None,
        should_cancel: Callable[[], bool] | None = None,
    ) -> VectorIndexResult:
        chunks = self._load_pending_chunks(document_index_id)
        total_count = self._total_chunk_count(document_index_id)

        if not chunks:
            self._mark_completed(document_index_id)

            return VectorIndexResult(
                document_index_id=document_index_id,
                indexed_count=0,
                total_count=total_count,
                reused=True,
            )

        self._mark_embedding(document_index_id)
        indexed_count = 0

        try:
            for offset in range(0, len(chunks), self.batch_size):
                if should_cancel and should_cancel():
                    raise InterruptedError("用户取消了向量化任务")

                batch = chunks[offset:offset + self.batch_size]
                documents = [
                    self._to_document(chunk)
                    for chunk in batch
                ]
                vector_ids = [
                    vector_id_for(
                        document_index_id=chunk.document_index_id,
                        chunk_number=chunk.chunk_number,
                        content_sha256=chunk.content_sha256,
                    )
                    for chunk in batch
                ]

                # Chroma 使用稳定 ID；重试时会覆盖相同 ID，
                # 不会无限生成重复向量。
                self.vector_store.add_documents(
                    documents=documents,
                    ids=vector_ids,
                )

                # 只有 Chroma 写入成功后才回写 SQLite。
                self._save_vector_ids(
                    chunks=batch,
                    vector_ids=vector_ids,
                )

                indexed_count += len(batch)

                if progress:
                    progress(
                        int(indexed_count / len(chunks) * 100)
                    )

            self._mark_completed(document_index_id)

        except InterruptedError:
            self._mark_parsed(
                document_index_id,
                "向量化被用户取消，可继续重试",
            )
            raise
        except Exception as exc:
            self._mark_parsed(
                document_index_id,
                f"向量化失败：{exc}",
            )
            raise

        return VectorIndexResult(
            document_index_id=document_index_id,
            indexed_count=indexed_count,
            total_count=total_count,
            reused=False,
        )

    def delete_document_vectors(
        self,
        document_index_id: int,
    ) -> int:
        with self.database.session() as session:
            chunks = list(
                session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_index_id
                        == document_index_id,
                        DocumentChunk.vector_id.is_not(None),
                    )
                )
            )
            vector_ids = [
                chunk.vector_id
                for chunk in chunks
                if chunk.vector_id
            ]

        if vector_ids:
            self.vector_store.delete(ids=vector_ids)

        with self.database.session() as session:
            stored_chunks = list(
                session.scalars(
                    select(DocumentChunk).where(
                        DocumentChunk.document_index_id
                        == document_index_id
                    )
                )
            )

            for chunk in stored_chunks:
                chunk.vector_id = None

            index = session.get(DocumentIndex, document_index_id)
            if index is not None:
                index.status = "parsed"
                index.updated_at = datetime.now()

        return len(vector_ids)

    def _load_pending_chunks(
        self,
        document_index_id: int,
    ) -> list[DocumentChunk]:
        with self.database.session() as session:
            index = session.get(DocumentIndex, document_index_id)

            if index is None:
                raise ValueError("文档索引不存在")

            if index.embedding_model != self.embedding_model:
                raise ValueError(
                    "文档索引的 Embedding 模型与当前配置不一致"
                )

            rows = list(
                session.scalars(
                    select(DocumentChunk)
                    .where(
                        DocumentChunk.document_index_id
                        == document_index_id,
                        DocumentChunk.vector_id.is_(None),
                    )
                    .order_by(DocumentChunk.chunk_number)
                )
            )

            # 返回脱离 Session 后仍可使用的对象。
            return [
                DocumentChunk(
                    id=row.id,
                    document_index_id=row.document_index_id,
                    resource_id=row.resource_id,
                    course_id=row.course_id,
                    chunk_number=row.chunk_number,
                    content=row.content,
                    content_sha256=row.content_sha256,
                    page_start=row.page_start,
                    page_end=row.page_end,
                    line_start=row.line_start,
                    line_end=row.line_end,
                    section_title=row.section_title,
                    location_label=row.location_label,
                    metadata_json=row.metadata_json,
                    vector_id=row.vector_id,
                    token_count=row.token_count,
                    created_at=row.created_at,
                )
                for row in rows
            ]

    def _to_document(self, chunk: DocumentChunk) -> Document:
        stored_metadata = json.loads(chunk.metadata_json or "{}")
        retrieval_text = str(
            stored_metadata.pop("retrieval_text", chunk.content)
        )

        metadata: dict[str, Any] = {
            "chunk_id": chunk.id,
            "document_index_id": chunk.document_index_id,
            "resource_id": chunk.resource_id,
            "course_id": chunk.course_id if chunk.course_id is not None else -1,
            "chunk_number": chunk.chunk_number,
            "content_sha256": chunk.content_sha256,
            "source_name": stored_metadata.get("source_name", ""),
            "file_type": stored_metadata.get("file_type", ""),
            "location_label": chunk.location_label,
            "section_title": chunk.section_title,
            "page_start": (
                chunk.page_start
                if chunk.page_start is not None
                else -1
            ),
            "page_end": (
                chunk.page_end
                if chunk.page_end is not None
                else -1
            ),
            "line_start": (
                chunk.line_start
                if chunk.line_start is not None
                else -1
            ),
            "line_end": (
                chunk.line_end
                if chunk.line_end is not None
                else -1
            ),
        }

        # Chroma metadata 只保存标量，不能直接保存嵌套 dict/list/None。
        for key in (
            "extraction_method",
            "ocr_confidence",
            "slide_number",
            "paragraph_number",
        ):
            value = stored_metadata.get(key)
            if isinstance(value, (str, int, float, bool)):
                metadata[key] = value

        return Document(
            page_content=retrieval_text,
            metadata=metadata,
        )

    def _save_vector_ids(
        self,
        *,
        chunks: list[DocumentChunk],
        vector_ids: list[str],
    ) -> None:
        with self.database.session() as session:
            for chunk, vector_id in zip(
                chunks,
                vector_ids,
                strict=True,
            ):
                stored = session.get(DocumentChunk, chunk.id)
                if stored is None:
                    raise RuntimeError(
                        f"文档片段不存在：{chunk.id}"
                    )
                stored.vector_id = vector_id

    def _total_chunk_count(self, document_index_id: int) -> int:
        with self.database.session() as session:
            index = session.get(DocumentIndex, document_index_id)
            if index is None:
                raise ValueError("文档索引不存在")
            return index.chunk_count

    def _mark_embedding(self, document_index_id: int) -> None:
        self._update_status(
            document_index_id,
            status="embedding",
            error="",
        )

    def _mark_completed(self, document_index_id: int) -> None:
        self._update_status(
            document_index_id,
            status="completed",
            error="",
        )

    def search(
        self,
        query: str,
        *,
        limit: int = 20,
        course_id: int | None = None,
        resource_ids: list[int] | None = None,
    ) -> list[SemanticHit]:
        chroma_filter = self._build_filter(
            course_id=course_id,
            resource_ids=resource_ids,
        )

        # 多取一些，以便剔除 stale、已删除或状态异常的数据。
        fetch_limit = max(limit * 3, limit)

        arguments: dict[str, object] = {
            "query": query,
            "k": fetch_limit,
        }

        if chroma_filter is not None:
            arguments["filter"] = chroma_filter

        results = self.vector_store.similarity_search_with_score(
            **arguments
        )

        candidate_ids: list[tuple[int, float]] = []

        for document, distance in results:
            raw_chunk_id = document.metadata.get("chunk_id")

            try:
                chunk_id = int(raw_chunk_id)
            except (TypeError, ValueError):
                continue

            candidate_ids.append((chunk_id, float(distance)))

        valid_ids = self._valid_completed_chunk_ids(
            [chunk_id for chunk_id, _ in candidate_ids],
            course_id=course_id,
            resource_ids=resource_ids,
        )

        hits: list[SemanticHit] = []

        for chunk_id, distance in candidate_ids:
            if chunk_id not in valid_ids:
                continue

            hits.append(
                SemanticHit(
                    chunk_id=chunk_id,
                    rank=len(hits) + 1,
                    distance=distance,
                )
            )

            if len(hits) >= limit:
                break

        return hits

    def _valid_completed_chunk_ids(
        self,
        chunk_ids: list[int],
        *,
        course_id: int | None,
        resource_ids: list[int] | None,
    ) -> set[int]:
        if not chunk_ids:
            return set()

        with self.database.session() as session:
            statement = (
                select(DocumentChunk.id)
                .join(
                    DocumentIndex,
                    DocumentIndex.id
                    == DocumentChunk.document_index_id,
                )
                .join(
                    ResourceFile,
                    ResourceFile.id == DocumentChunk.resource_id,
                )
                .where(
                    DocumentChunk.id.in_(chunk_ids),
                    DocumentIndex.status == "completed",
                    DocumentChunk.vector_id.is_not(None),
                    ResourceFile.trashed.is_(False),
                )
            )
            if course_id is not None:
                statement = statement.where(
                    ResourceFile.course_id == course_id
                )
            if resource_ids:
                statement = statement.where(
                    DocumentChunk.resource_id.in_(resource_ids)
                )
            rows = session.execute(statement).all()

        return {int(row[0]) for row in rows}

    @staticmethod
    def _build_filter(
        *,
        course_id: int | None,
        resource_ids: list[int] | None,
    ) -> dict[str, object] | None:
        conditions: list[dict[str, object]] = []

        if resource_ids:
            conditions.append({
                "resource_id": {"$in": resource_ids},
            })

        if not conditions:
            return None

        if len(conditions) == 1:
            return conditions[0]

        return {"$and": conditions}

    def _mark_parsed(
        self,
        document_index_id: int,
        error: str,
    ) -> None:
        self._update_status(
            document_index_id,
            status="parsed",
            error=error,
        )

    def _update_status(
        self,
        document_index_id: int,
        *,
        status: str,
        error: str,
    ) -> None:
        with self.database.session() as session:
            index = session.get(DocumentIndex, document_index_id)

            if index is None:
                return

            index.status = status
            index.error_message = error[:4000]
            index.updated_at = datetime.now()

            if status == "completed":
                index.completed_at = datetime.now()
