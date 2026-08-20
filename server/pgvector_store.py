from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session


@dataclass(frozen=True, slots=True)
class VectorHit:
    chunk_id: int
    distance: float


class PgVectorStore:
    """Tenant-scoped pgvector storage used by workers and RAG retrieval."""

    def __init__(self, session: Session, *, dimensions: int = 512) -> None:
        self.session = session
        self.dimensions = dimensions

    def upsert(
        self,
        *,
        tenant_id: str,
        chunk_id: int,
        embedding_model: str,
        embedding_version: str,
        content_sha256: str,
        embedding: Sequence[float],
    ) -> None:
        self._validate_embedding(embedding)
        self.session.execute(
            text(
                """
                INSERT INTO document_embeddings
                    (tenant_id, chunk_id, embedding_model, embedding_version, content_sha256, embedding)
                VALUES (:tenant_id, :chunk_id, :embedding_model, :embedding_version, :content_sha256, CAST(:embedding AS vector))
                ON CONFLICT (chunk_id, embedding_version) DO UPDATE SET
                    tenant_id = EXCLUDED.tenant_id,
                    embedding_model = EXCLUDED.embedding_model,
                    content_sha256 = EXCLUDED.content_sha256,
                    embedding = EXCLUDED.embedding
                """
            ),
            {
                "tenant_id": tenant_id,
                "chunk_id": chunk_id,
                "embedding_model": embedding_model,
                "embedding_version": embedding_version,
                "content_sha256": content_sha256,
                "embedding": self._vector_literal(embedding),
            },
        )

    def search(
        self, *, tenant_id: str, embedding_version: str, query_embedding: Sequence[float], limit: int,
        course_id: int | None = None, resource_ids: Sequence[int] | None = None,
    ) -> list[VectorHit]:
        self._validate_embedding(query_embedding)
        predicates = [
            "tenant_id = :tenant_id",
            "embedding_version = :embedding_version",
        ]
        params: dict[str, object] = {
            "tenant_id": tenant_id,
            "embedding_version": embedding_version,
            "embedding": self._vector_literal(query_embedding),
            "limit": limit,
        }
        if course_id is not None:
            predicates.append(
                "EXISTS (SELECT 1 FROM document_chunks dc "
                "WHERE dc.id = document_embeddings.chunk_id "
                "AND dc.tenant_id = :tenant_id AND dc.course_id = :course_id)"
            )
            params["course_id"] = course_id
        if resource_ids:
            placeholders = []
            for index, resource_id in enumerate(resource_ids):
                key = f"resource_id_{index}"
                placeholders.append(f":{key}")
                params[key] = int(resource_id)
            predicates.append(
                "EXISTS (SELECT 1 FROM document_chunks dc "
                "WHERE dc.id = document_embeddings.chunk_id "
                "AND dc.tenant_id = :tenant_id "
                f"AND dc.resource_id IN ({', '.join(placeholders)}))"
            )
        rows = self.session.execute(
            text(
                f"""
                SELECT chunk_id, embedding <=> CAST(:embedding AS vector) AS distance
                FROM document_embeddings
                WHERE {' AND '.join(predicates)}
                ORDER BY embedding <=> CAST(:embedding AS vector)
                LIMIT :limit
                """
            ),
            params,
        )
        return [VectorHit(chunk_id=int(row.chunk_id), distance=float(row.distance)) for row in rows]

    def _validate_embedding(self, embedding: Sequence[float]) -> None:
        if len(embedding) != self.dimensions:
            raise ValueError(f"expected {self.dimensions} embedding dimensions, got {len(embedding)}")

    @staticmethod
    def _vector_literal(embedding: Sequence[float]) -> str:
        return "[" + ",".join(format(float(value), ".10g") for value in embedding) + "]"
