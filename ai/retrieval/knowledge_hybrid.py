from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from sqlalchemy import select

from ai.retrieval.knowledge_store import (
    KnowledgeKeywordHit,
    KnowledgePointVectorIndex,
    KnowledgeSemanticHit,
    SQLiteKnowledgePointIndex,
)
from app.database import Database
from app.models import KnowledgePoint

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class KnowledgeRetrievalHit:
    knowledge_point_id: int
    course_id: int
    name: str
    category: str
    definition: str
    formula: str
    prerequisites: tuple[str, ...]
    related_points: tuple[str, ...]
    common_mistakes: tuple[str, ...]
    difficulty: int
    importance: int
    confidence: float
    rrf_score: float
    keyword_rank: int | None
    semantic_rank: int | None
    keyword_score: float | None
    semantic_distance: float | None


class KnowledgePointHybridRetriever:
    def __init__(
        self,
        *,
        database: Database,
        keyword_index: SQLiteKnowledgePointIndex,
        vector_index: KnowledgePointVectorIndex,
        rrf_k: int = 60,
        keyword_weight: float = 1.0,
        semantic_weight: float = 1.0,
    ) -> None:
        self.database = database
        self.keyword_index = keyword_index
        self.vector_index = vector_index
        self.rrf_k = rrf_k
        self.keyword_weight = keyword_weight
        self.semantic_weight = semantic_weight

    def retrieve(
        self,
        query: str,
        *,
        limit: int = 8,
        candidate_limit: int = 30,
        course_id: int | None = None,
    ) -> list[KnowledgeRetrievalHit]:
        if not query.strip():
            return []
        keyword_hits = self.keyword_index.search(
            query, limit=candidate_limit, course_id=course_id
        )
        try:
            semantic_hits = self.vector_index.search(
                query, limit=candidate_limit, course_id=course_id
            )
        except Exception:
            logger.warning("知识点语义检索不可用，已降级为关键词检索", exc_info=True)
            semantic_hits = []
        keyword_by_id: dict[int, KnowledgeKeywordHit] = {
            hit.knowledge_point_id: hit for hit in keyword_hits
        }
        semantic_by_id: dict[int, KnowledgeSemanticHit] = {
            hit.knowledge_point_id: hit for hit in semantic_hits
        }
        scores: dict[int, float] = {}
        for hit in keyword_hits:
            scores[hit.knowledge_point_id] = scores.get(hit.knowledge_point_id, 0) + (
                self.keyword_weight / (self.rrf_k + hit.rank)
            )
        for hit in semantic_hits:
            scores[hit.knowledge_point_id] = scores.get(hit.knowledge_point_id, 0) + (
                self.semantic_weight / (self.rrf_k + hit.rank)
            )
        ids = sorted(scores, key=lambda item: (-scores[item], item))[:limit]
        if not ids:
            return []
        with self.database.session() as session:
            points = list(session.scalars(
                select(KnowledgePoint).where(KnowledgePoint.id.in_(ids))
            ))
        by_id = {point.id: point for point in points}

        def array(raw: str) -> tuple[str, ...]:
            try:
                value = json.loads(raw or "[]")
                return tuple(str(item) for item in value) if isinstance(value, list) else ()
            except json.JSONDecodeError:
                return ()

        result = []
        for point_id in ids:
            point = by_id.get(point_id)
            if point is None:
                continue
            keyword = keyword_by_id.get(point_id)
            semantic = semantic_by_id.get(point_id)
            result.append(KnowledgeRetrievalHit(
                knowledge_point_id=point.id,
                course_id=point.course_id,
                name=point.name,
                category=point.category,
                definition=point.definition,
                formula=point.formula,
                prerequisites=array(point.prerequisites_json),
                related_points=array(point.related_points_json),
                common_mistakes=array(point.common_mistakes_json),
                difficulty=point.difficulty,
                importance=point.importance,
                confidence=point.confidence,
                rrf_score=scores[point_id],
                keyword_rank=keyword.rank if keyword else None,
                semantic_rank=semantic.rank if semantic else None,
                keyword_score=keyword.bm25_score if keyword else None,
                semantic_distance=semantic.distance if semantic else None,
            ))
        return result
