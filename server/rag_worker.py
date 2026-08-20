from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.orm import Session

from app.models import AICitation, AIRun
from app.agent_runtime import AgentBudget
from ai.retrieval.agentic import AgenticRAG
from server.rag_retriever import TenantPgVectorRetriever
from ai.gateways.rerank import Reranker
from server.tenant_session import set_session_tenant


def has_valid_citations(answer: str, evidence_count: int) -> bool:
    """Accept generated answers only when every cited source is retrieved evidence."""
    citations = [int(number) for number in re.findall(r"\[(\d+)\]", answer)]
    return bool(citations) and all(1 <= number <= evidence_count for number in citations)


def retrieve_rag_evidence(
    *,
    payload: dict[str, object],
    session_factory: Callable[[], Session],
    embeddings: Embeddings,
    embedding_version: str,
    dimensions: int,
    model_name: str,
    chat_model: BaseChatModel | None = None,
    chat_provider: str = "",
    chat_model_name: str = "",
    reranker: Reranker | None = None,
    rerank_candidate_limit: int = 24,
    query_rewrite_enabled: bool = True,
    hybrid_retrieval_enabled: bool = True,
    agentic_rag_enabled: bool = True,
) -> dict[str, object]:
    """Persist tenant-scoped evidence and optionally generate a grounded answer."""
    tenant_id = str(payload["tenant_id"])
    question = str(payload["question"]).strip()
    if not question:
        raise ValueError("question is required")
    course_id = payload.get("course_id")
    with session_factory() as session:
        set_session_tenant(session, tenant_id)
        retriever = TenantPgVectorRetriever(
            session=session,
            embeddings=embeddings,
            embedding_version=embedding_version,
            dimensions=dimensions,
            reranker=reranker,
            rerank_candidate_limit=rerank_candidate_limit,
            query_rewrite_enabled=query_rewrite_enabled,
            hybrid_retrieval_enabled=hybrid_retrieval_enabled,
        )
        retrieval_filters = {
            "tenant_id": tenant_id,
            "course_id": int(course_id) if course_id is not None else None,
        }
        if agentic_rag_enabled:
            hits, retrieval_observations = AgenticRAG(
                retriever.retrieve, budget=AgentBudget(max_rag_searches=4),
            ).search(question, **retrieval_filters)
        else:
            hits = retriever.retrieve(question, **retrieval_filters)
            retrieval_observations = []
        answer = ""
        generation_status = "evidence_only"
        if chat_model is not None and hits:
            evidence = "\n\n".join(
                f"[{number}] {hit.content[:1500]}" for number, hit in enumerate(hits, start=1)
            )
            prompt = (
                "你是学习资料问答助手。只能依据给出的资料回答，不确定时明确说明。"
                "回答使用中文，并在对应结论后以 [编号] 标明资料来源。\n\n"
                f"问题：{question}\n\n资料：\n{evidence}"
            )
            response = chat_model.invoke(prompt)
            content = response.content
            candidate = content if isinstance(content, str) else str(content)
            if has_valid_citations(candidate, len(hits)):
                answer = candidate
                generation_status = "generated"
        run = AIRun(
            tenant_id=tenant_id,
            run_uuid=str(uuid4()),
            feature="document_qa_retrieval",
            status="completed",
            provider=chat_provider if generation_status == "generated" else "pgvector",
            model_name=chat_model_name if generation_status == "generated" else model_name,
            prompt_version="saas-rag-grounded-v1" if generation_status == "generated" else "saas-rag-retrieval-v1",
            input_json=json.dumps({"question": question, "course_id": course_id}, ensure_ascii=False),
            output_json=json.dumps({
                "mode": generation_status,
                "answer": answer,
                "evidence_count": len(hits),
                "chunk_ids": [hit.chunk_id for hit in hits],
                "retrieval_observations": [item.__dict__ for item in retrieval_observations],
            }, ensure_ascii=False),
            course_id=int(course_id) if course_id is not None else None,
            finished_at=datetime.now(),
        )
        session.add(run)
        session.flush()
        for number, hit in enumerate(hits, start=1):
            session.add(AICitation(
                tenant_id=tenant_id,
                ai_run_id=run.id,
                chunk_id=hit.chunk_id,
                citation_number=number,
                quote_text=hit.content[:1000],
                relevance_score=hit.rrf_score,
            ))
        session.commit()
        return {
            "ai_run_id": run.id,
            "mode": generation_status,
            "answer": answer,
            "evidence_count": len(hits),
            "chunk_ids": [hit.chunk_id for hit in hits],
            "retrieval_observations": [item.__dict__ for item in retrieval_observations],
        }
