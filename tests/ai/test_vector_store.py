from __future__ import annotations

import json

from langchain_core.embeddings import Embeddings
from sqlalchemy import select

from ai.retrieval import ChromaVectorIndex, vector_id_for
from app.database import Database
from app.models import (
    DocumentChunk,
    DocumentIndex,
    ResourceFile,
)


class FakeEmbeddings(Embeddings):
    def embed_documents(
        self,
        texts: list[str],
    ) -> list[list[float]]:
        return [[float(len(text)), 1.0, 0.0] for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return [float(len(text)), 1.0, 0.0]


class FakeVectorStore:
    def __init__(self) -> None:
        self.documents = {}
        self.deleted_ids: list[str] = []

    def add_documents(self, *, documents, ids):
        for vector_id, document in zip(ids, documents, strict=True):
            self.documents[vector_id] = document
        return ids

    def delete(self, *, ids):
        self.deleted_ids.extend(ids)
        for vector_id in ids:
            self.documents.pop(vector_id, None)


def prepare_document(database: Database) -> int:
    with database.session() as session:
        resource = ResourceFile(
            name="教材.txt",
            original_name="教材.txt",
            source_path="",
            relative_path="教材.txt",
            sha256="a" * 64,
            size=100,
            course_id=None,
            tags="",
        )
        session.add(resource)
        session.flush()

        index = DocumentIndex(
            resource_id=resource.id,
            status="parsed",
            parser_version="test-parser",
            chunker_version="test-chunker",
            embedding_model="test-embedding",
            source_sha256=resource.sha256,
            chunk_count=2,
        )
        session.add(index)
        session.flush()

        for number, text in enumerate(["函数极限", "函数连续"]):
            session.add(
                DocumentChunk(
                    document_index_id=index.id,
                    resource_id=resource.id,
                    course_id=None,
                    chunk_number=number,
                    content=text,
                    content_sha256=str(number + 1) * 64,
                    location_label=f"第 {number + 1} 页",
                    metadata_json=json.dumps(
                        {
                            "retrieval_text": text,
                            "source_name": "教材.txt",
                            "file_type": "txt",
                        },
                        ensure_ascii=False,
                    ),
                )
            )

        return index.id


def test_vectors_are_written_before_sqlite_ids(tmp_path) -> None:
    database = Database(
        f"sqlite:///{(tmp_path / 'vectors.db').as_posix()}"
    )
    database.create_schema()
    document_index_id = prepare_document(database)
    fake_store = FakeVectorStore()

    service = ChromaVectorIndex(
        database=database,
        embeddings=FakeEmbeddings(),
        persist_directory=tmp_path / "chroma",
        embedding_model="test-embedding",
        batch_size=1,
        vector_store=fake_store,
    )

    result = service.index_document(document_index_id)

    assert result.indexed_count == 2
    assert len(fake_store.documents) == 2

    with database.session() as session:
        index = session.get(DocumentIndex, document_index_id)
        chunks = list(
            session.scalars(
                select(DocumentChunk)
                .where(
                    DocumentChunk.document_index_id
                    == document_index_id
                )
                .order_by(DocumentChunk.chunk_number)
            )
        )

        assert index is not None
        assert index.status == "completed"
        assert all(chunk.vector_id for chunk in chunks)
        assert set(chunk.vector_id for chunk in chunks) == set(
            fake_store.documents
        )

    database.close()


def test_completed_vectors_are_reused(tmp_path) -> None:
    database = Database(
        f"sqlite:///{(tmp_path / 'reuse.db').as_posix()}"
    )
    database.create_schema()
    document_index_id = prepare_document(database)
    fake_store = FakeVectorStore()

    service = ChromaVectorIndex(
        database=database,
        embeddings=FakeEmbeddings(),
        persist_directory=tmp_path / "chroma",
        embedding_model="test-embedding",
        vector_store=fake_store,
    )

    first = service.index_document(document_index_id)
    second = service.index_document(document_index_id)

    assert first.indexed_count == 2
    assert second.indexed_count == 0
    assert second.reused is True
    assert len(fake_store.documents) == 2

    database.close()


def test_vector_id_is_stable() -> None:
    first = vector_id_for(
        document_index_id=7,
        chunk_number=3,
        content_sha256="a" * 64,
    )
    second = vector_id_for(
        document_index_id=7,
        chunk_number=3,
        content_sha256="a" * 64,
    )

    assert first == second