from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import date
from uuid import uuid4

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from ai.gateways.rerank import Reranker
from app.models import ReviewItem
from server.rag_retriever import TenantPgVectorRetriever
from server.tenant_session import set_session_tenant


def generate_vocabulary(*, payload: dict[str, object], session_factory: Callable[[], Session], embeddings: Embeddings,
                        embedding_version: str, dimensions: int, chat_model: BaseChatModel,
                        reranker: Reranker | None = None, rerank_candidate_limit: int = 24,
                        query_rewrite_enabled: bool = True, hybrid_retrieval_enabled: bool = True) -> dict[str, object]:
    tenant_id = str(payload["tenant_id"]); course_id = int(payload["course_id"])
    count = max(1, min(30, int(payload.get("count", 10))))
    request = str(payload.get("request", "核心词汇")).strip()
    with session_factory() as session:
        set_session_tenant(session, tenant_id)
        retriever = TenantPgVectorRetriever(session=session, embeddings=embeddings, embedding_version=embedding_version,
            dimensions=dimensions, reranker=reranker, rerank_candidate_limit=rerank_candidate_limit,
            query_rewrite_enabled=query_rewrite_enabled, hybrid_retrieval_enabled=hybrid_retrieval_enabled)
        hits = retriever.retrieve(request, tenant_id=tenant_id, course_id=course_id)
        if not hits: raise ValueError("no indexed course evidence found; upload and index resources first")
        evidence = "\n\n".join(f"[{i}] {hit.content[:1800]}" for i, hit in enumerate(hits, 1))
        prompt = ("Return JSON only: {\"words\":[{\"word\":\"\",\"meaning\":\"\",\"example\":\"\",\"citations\":[1]}]}. "
                  f"Generate exactly {count} useful vocabulary items from the evidence. Request: {request}. Evidence:\n{evidence}")
        raw = chat_model.invoke(prompt).content
        text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", str(raw), flags=re.I)
        decoded = json.loads(text); words = decoded.get("words", [])
        if not isinstance(words, list): raise ValueError("invalid vocabulary response")
        created = []
        existing = {x.title.casefold() for x in session.scalars(select(ReviewItem).where(ReviewItem.tenant_id == tenant_id, ReviewItem.source == "vocabulary")).all()}
        for item in words[:count]:
            if not isinstance(item, dict): continue
            word = str(item.get("word", "")).strip()
            meaning = str(item.get("meaning", "")).strip()
            if not word or not meaning or word.casefold() in existing: continue
            row = ReviewItem(tenant_id=tenant_id, title=word[:180], note=f"{meaning}\n{str(item.get('example', '')).strip()}".strip(), source="vocabulary", next_review=date.today())
            session.add(row); session.flush(); created.append(row.id); existing.add(word.casefold())
        session.commit()
        return {"count": len(created), "review_item_ids": created, "evidence_count": len(hits)}
