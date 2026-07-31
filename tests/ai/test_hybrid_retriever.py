from __future__ import annotations

from ai.retrieval.hybrid import HybridRetriever
from ai.retrieval.keyword_store import KeywordHit
from ai.retrieval.vector_store import SemanticHit


class FakeKeywordIndex:
    def search(self, query, **kwargs):
        return [
            KeywordHit(chunk_id=1, rank=1, bm25_score=-2.0),
            KeywordHit(chunk_id=2, rank=2, bm25_score=-1.0),
        ]


class FakeVectorIndex:
    def search(self, query, **kwargs):
        return [
            SemanticHit(chunk_id=2, rank=1, distance=0.1),
            SemanticHit(chunk_id=3, rank=2, distance=0.2),
        ]


def test_rrf_rewards_chunks_found_by_both_retrievers() -> None:
    retriever = HybridRetriever(
        database=None,  # 此测试只验证融合分数
        keyword_index=FakeKeywordIndex(),
        vector_index=FakeVectorIndex(),
        rrf_k=60,
    )

    keyword_hits = retriever.keyword_index.search("极限")
    semantic_hits = retriever.vector_index.search("极限")

    scores: dict[int, float] = {}

    for hit in keyword_hits:
        scores[hit.chunk_id] = (
            scores.get(hit.chunk_id, 0.0)
            + 1 / (60 + hit.rank)
        )

    for hit in semantic_hits:
        scores[hit.chunk_id] = (
            scores.get(hit.chunk_id, 0.0)
            + 1 / (60 + hit.rank)
        )

    ranked = sorted(scores, key=scores.get, reverse=True)

    assert ranked[0] == 2