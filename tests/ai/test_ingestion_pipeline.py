from __future__ import annotations

import json

from sqlalchemy import func, select

from ai.ingestion import (
    CitationAwareSplitter,
    DocumentIngestionPipeline,
    DocumentParserRegistry,
)
from app.database import Database
from app.models import DocumentChunk, DocumentIndex, ResourceFile


def build_pipeline(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    database = Database(
        f"sqlite:///{(tmp_path / 'learning.db').as_posix()}"
    )
    database.create_schema()

    pipeline = DocumentIngestionPipeline(
        database=database,
        workspace_dir=workspace,
        parser_registry=DocumentParserRegistry(ocr_enabled=False),
        splitter=CitationAwareSplitter(
            chunk_size=300,
            chunk_overlap=50,
        ),
        embedding_model="test-embedding",
    )

    return database, workspace, pipeline


def add_resource(
    database: Database,
    workspace,
    *,
    name: str,
    content: str,
) -> int:
    path = workspace / name
    path.write_text(content, encoding="utf-8")

    with database.session() as session:
        resource = ResourceFile(
            name=name,
            original_name=name,
            source_path="",
            relative_path=name,
            sha256="original-import-hash",
            size=path.stat().st_size,
            course_id=None,
            tags="",
            trashed=False,
        )
        session.add(resource)
        session.flush()
        return resource.id


def test_ingestion_stores_chunks_and_locations(tmp_path) -> None:
    database, workspace, pipeline = build_pipeline(tmp_path)

    resource_id = add_resource(
        database,
        workspace,
        name="笔记.md",
        content=(
            "# 极限\n"
            + "极限描述函数值的变化趋势。" * 100
            + "\n\n"
            + "## 连续\n"
            + "连续函数可以使用极限描述。" * 100
        ),
    )

    result = pipeline.ingest(resource_id)

    assert result.status == "completed"
    assert result.reused is False
    assert result.chunk_count > 1

    with database.session() as session:
        index = session.get(DocumentIndex, result.document_index_id)
        chunks = list(
            session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_index_id
                    == result.document_index_id
                )
                .order_by(DocumentChunk.chunk_number)
            )
        )

        assert index is not None
        assert index.status == "completed"
        assert index.chunk_count == len(chunks)

        assert [chunk.chunk_number for chunk in chunks] == list(
            range(len(chunks))
        )
        assert all(chunk.location_label for chunk in chunks)
        assert all(len(chunk.content_sha256) == 64 for chunk in chunks)

        metadata = json.loads(chunks[0].metadata_json)
        assert metadata["source_name"] == "笔记.md"
        assert metadata["retrieval_text"]

    database.close()


def test_second_ingestion_reuses_completed_index(tmp_path) -> None:
    database, workspace, pipeline = build_pipeline(tmp_path)

    resource_id = add_resource(
        database,
        workspace,
        name="笔记.txt",
        content="函数极限描述函数的变化趋势。" * 50,
    )

    first = pipeline.ingest(resource_id)
    second = pipeline.ingest(resource_id)

    assert first.reused is False
    assert second.reused is True
    assert second.document_index_id == first.document_index_id

    with database.session() as session:
        index_count = session.scalar(
            select(func.count()).select_from(DocumentIndex)
        )

        chunk_count = session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.document_index_id
                == first.document_index_id
            )
        )

        assert index_count == 1
        assert chunk_count == first.chunk_count

    database.close()


def test_force_ingestion_replaces_chunks_without_duplication(
    tmp_path,
) -> None:
    database, workspace, pipeline = build_pipeline(tmp_path)

    resource_id = add_resource(
        database,
        workspace,
        name="复习.txt",
        content="导数描述函数的瞬时变化率。" * 80,
    )

    first = pipeline.ingest(resource_id)
    second = pipeline.ingest(resource_id, force=True)

    assert second.reused is False
    assert second.document_index_id == first.document_index_id
    assert second.chunk_count == first.chunk_count

    with database.session() as session:
        chunk_count = session.scalar(
            select(func.count())
            .select_from(DocumentChunk)
            .where(
                DocumentChunk.document_index_id
                == first.document_index_id
            )
        )

        assert chunk_count == first.chunk_count

    database.close()