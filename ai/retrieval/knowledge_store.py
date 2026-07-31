from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from sqlalchemy import select, text

from ai.retrieval.keyword_store import build_fts_query, tokenize_for_search
from ai.retrieval.vector_store import collection_name_for
from app.database import Database
from app.models import KnowledgePoint


@dataclass(frozen=True, slots=True)
class KnowledgeKeywordHit:
    knowledge_point_id: int
    rank: int
    bm25_score: float


@dataclass(frozen=True, slots=True)
class KnowledgeSemanticHit:
    knowledge_point_id: int
    rank: int
    distance: float


def knowledge_vector_id(knowledge_point_id: int) -> str:
    return f"knowledge-point-{knowledge_point_id}"


def knowledge_search_text(point: KnowledgePoint) -> str:
    def values(raw: str) -> str:
        try:
            value = json.loads(raw or "[]")
            return "、".join(str(item) for item in value) if isinstance(value, list) else ""
        except json.JSONDecodeError:
            return ""

    parts = [
        f"知识点：{point.name}",
        f"类型：{point.category}",
        f"定义：{point.definition}",
    ]
    if point.formula:
        parts.append(f"公式：{point.formula}")
    prerequisites = values(point.prerequisites_json)
    related = values(point.related_points_json)
    mistakes = values(point.common_mistakes_json)
    if prerequisites:
        parts.append(f"前置知识：{prerequisites}")
    if related:
        parts.append(f"相关知识：{related}")
    if mistakes:
        parts.append(f"常见错误：{mistakes}")
    return "\n".join(parts)


class SQLiteKnowledgePointIndex:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.ensure_schema()

    def ensure_schema(self) -> None:
        with self.database.engine.begin() as connection:
            try:
                connection.exec_driver_sql(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_points_fts
                    USING fts5(
                        knowledge_point_id UNINDEXED,
                        course_id UNINDEXED,
                        search_text,
                        tokenize='unicode61 remove_diacritics 2'
                    )
                    """
                )
            except Exception as exc:
                raise RuntimeError("当前 SQLite 不支持 FTS5，无法建立知识点索引") from exc

    def upsert(self, point: KnowledgePoint) -> None:
        tokenized = " ".join(tokenize_for_search(knowledge_search_text(point)))
        with self.database.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM knowledge_points_fts WHERE knowledge_point_id = :id"),
                {"id": point.id},
            )
            if tokenized:
                connection.execute(
                    text(
                        """
                        INSERT INTO knowledge_points_fts
                            (knowledge_point_id, course_id, search_text)
                        VALUES (:id, :course_id, :search_text)
                        """
                    ),
                    {"id": point.id, "course_id": point.course_id, "search_text": tokenized},
                )

    def delete(self, knowledge_point_id: int) -> None:
        with self.database.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM knowledge_points_fts WHERE knowledge_point_id = :id"),
                {"id": knowledge_point_id},
            )

    def rebuild(self) -> int:
        with self.database.session() as session:
            points = list(session.scalars(select(KnowledgePoint)))
        with self.database.engine.begin() as connection:
            connection.exec_driver_sql("DELETE FROM knowledge_points_fts")
        for point in points:
            self.upsert(point)
        return len(points)

    def search(
        self, query: str, *, limit: int = 20, course_id: int | None = None
    ) -> list[KnowledgeKeywordHit]:
        fts_query = build_fts_query(query)
        if not fts_query:
            return []
        conditions = ["knowledge_points_fts MATCH :query"]
        parameters: dict[str, object] = {"query": fts_query, "limit": limit}
        if course_id is not None:
            conditions.append("CAST(f.course_id AS INTEGER) = :course_id")
            parameters["course_id"] = course_id
        statement = text(
            f"""
            SELECT CAST(f.knowledge_point_id AS INTEGER) AS knowledge_point_id,
                   bm25(knowledge_points_fts) AS score
            FROM knowledge_points_fts AS f
            JOIN knowledge_points AS kp
              ON kp.id = CAST(f.knowledge_point_id AS INTEGER)
            WHERE {' AND '.join(conditions)}
            ORDER BY score
            LIMIT :limit
            """
        )
        with self.database.engine.connect() as connection:
            rows = connection.execute(statement, parameters).fetchall()
        return [
            KnowledgeKeywordHit(int(row.knowledge_point_id), rank, float(row.score))
            for rank, row in enumerate(rows, 1)
        ]


class KnowledgePointVectorIndex:
    def __init__(
        self,
        *,
        database: Database,
        embeddings: Embeddings,
        persist_directory: Path,
        embedding_model: str,
        collection_prefix: str = "knowledge_points",
        vector_store: Any | None = None,
    ) -> None:
        self.database = database
        self.embedding_model = embedding_model
        self.persist_directory = persist_directory.resolve()
        self.persist_directory.mkdir(parents=True, exist_ok=True)
        self.collection_name = collection_name_for(collection_prefix, embedding_model)
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

    def upsert(self, knowledge_point_id: int) -> str:
        with self.database.session() as session:
            point = session.get(KnowledgePoint, knowledge_point_id)
            if point is None:
                raise ValueError("知识点不存在")
            vector_id = knowledge_vector_id(point.id)
            document = Document(
                page_content=knowledge_search_text(point),
                metadata={
                    "knowledge_point_id": point.id,
                    "course_id": point.course_id,
                    "name": point.name,
                    "category": point.category,
                    "difficulty": point.difficulty,
                    "importance": point.importance,
                },
            )
        self.vector_store.add_documents(documents=[document], ids=[vector_id])
        with self.database.session() as session:
            stored = session.get(KnowledgePoint, knowledge_point_id)
            if stored is None:
                raise RuntimeError("知识点在向量写入后被删除")
            stored.vector_id = vector_id
            stored.embedding_model = self.embedding_model
        return vector_id

    def delete(self, knowledge_point_id: int) -> None:
        self.vector_store.delete(ids=[knowledge_vector_id(knowledge_point_id)])
        with self.database.session() as session:
            point = session.get(KnowledgePoint, knowledge_point_id)
            if point:
                point.vector_id = None
                point.embedding_model = ""

    def search(
        self, query: str, *, limit: int = 20, course_id: int | None = None
    ) -> list[KnowledgeSemanticHit]:
        arguments: dict[str, object] = {"query": query, "k": max(limit * 3, limit)}
        if course_id is not None:
            arguments["filter"] = {"course_id": course_id}
        results = self.vector_store.similarity_search_with_score(**arguments)
        candidates = []
        for document, distance in results:
            try:
                point_id = int(document.metadata.get("knowledge_point_id"))
            except (TypeError, ValueError):
                continue
            candidates.append((point_id, float(distance)))
        if not candidates:
            return []
        with self.database.session() as session:
            valid = set(session.scalars(
                select(KnowledgePoint.id).where(
                    KnowledgePoint.id.in_([item[0] for item in candidates]),
                    KnowledgePoint.vector_id.is_not(None),
                    KnowledgePoint.embedding_model == self.embedding_model,
                )
            ))
        hits = []
        for point_id, distance in candidates:
            if point_id in valid:
                hits.append(KnowledgeSemanticHit(point_id, len(hits) + 1, distance))
            if len(hits) >= limit:
                break
        return hits


class KnowledgePointIndex:
    """保证 SQLite FTS 与 Chroma 两份索引同步更新。"""

    def __init__(
        self,
        *,
        database: Database,
        keywords: SQLiteKnowledgePointIndex,
        vectors: KnowledgePointVectorIndex,
    ) -> None:
        self.database = database
        self.keywords = keywords
        self.vectors = vectors

    def upsert(self, knowledge_point_id: int) -> str:
        with self.database.session() as session:
            point = session.get(KnowledgePoint, knowledge_point_id)
            if point is None:
                raise ValueError("知识点不存在")
            detached = KnowledgePoint(
                id=point.id,
                course_id=point.course_id,
                name=point.name,
                mastery=point.mastery,
                note=point.note,
                category=point.category,
                definition=point.definition,
                formula=point.formula,
                prerequisites_json=point.prerequisites_json,
                related_points_json=point.related_points_json,
                common_mistakes_json=point.common_mistakes_json,
                difficulty=point.difficulty,
                importance=point.importance,
                confidence=point.confidence,
                source=point.source,
                vector_id=point.vector_id,
                embedding_model=point.embedding_model,
            )
        vector_id = self.vectors.upsert(knowledge_point_id)
        self.keywords.upsert(detached)
        return vector_id

    def rebuild(self) -> int:
        with self.database.session() as session:
            ids = list(session.scalars(
                select(KnowledgePoint.id).order_by(KnowledgePoint.id)
            ))
        for knowledge_point_id in ids:
            self.vectors.upsert(knowledge_point_id)
        self.keywords.rebuild()
        return len(ids)
