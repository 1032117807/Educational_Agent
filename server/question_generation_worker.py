from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AICitation, AIRun, BackgroundJob, KnowledgePoint, Question, QuestionDraft, QuestionDraftCitation
from server.rag_retriever import TenantPgVectorRetriever
from ai.gateways.rerank import Reranker
from ai.usage import response_token_usage
from server.tenant_session import set_session_tenant


ALLOWED_QUESTION_KINDS = {
    "single_choice", "multiple_choice", "true_false", "fill_blank",
    "short_answer", "calculation", "essay", "reading",
}


def _json_object(content: object) -> dict[str, object]:
    text = content if isinstance(content, str) else str(content)
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text, flags=re.IGNORECASE)
    decoded = json.loads(text)
    if not isinstance(decoded, dict):
        raise ValueError("AI response must be a JSON object")
    return decoded


def _validate_question(item: object, evidence_count: int, *, allow_ungrounded: bool = False) -> dict[str, object]:
    if not isinstance(item, dict):
        raise ValueError("each generated question must be an object")
    prompt = str(item.get("prompt", "")).strip()
    answer = str(item.get("answer", "")).strip()
    kind = str(item.get("kind", "")).strip()
    explanation = str(item.get("explanation", "")).strip()
    citations = item.get("citations", [])
    if not prompt or not answer or kind not in ALLOWED_QUESTION_KINDS:
        raise ValueError("generated question has missing or unsupported fields")
    if not allow_ungrounded and (not isinstance(citations, list) or not citations):
        raise ValueError("every generated question requires evidence citations")
    citation_numbers = [int(value) for value in citations] if isinstance(citations, list) else []
    # A launch may intentionally create a clearly ungrounded baseline when a
    # course has no indexed materials. In that mode the model must not turn a
    # harmless placeholder citation into a validation failure; persist no
    # citations because there is no source to cite.
    if allow_ungrounded and evidence_count == 0:
        citation_numbers = []
    if any(number < 1 or number > evidence_count for number in citation_numbers):
        raise ValueError("generated question cites evidence outside the retrieved set")
    if not allow_ungrounded and not all(f"[{number}]" in explanation for number in citation_numbers):
        raise ValueError("question explanation must include its evidence citations")
    options = item.get("options", [])
    if kind in {"single_choice", "multiple_choice"}:
        if not isinstance(options, list) or len(options) < 2:
            raise ValueError("choice questions require at least two options")
        options_text = json.dumps([str(option) for option in options], ensure_ascii=False)
    else:
        options_text = "[]"
    tags = item.get("tags", [])
    tags_text = ", ".join(str(tag).strip() for tag in tags if str(tag).strip()) if isinstance(tags, list) else str(tags)
    difficulty = int(item.get("difficulty", 3))
    return {
        "prompt": prompt,
        "answer": answer,
        "kind": kind,
        "explanation": explanation,
        "options": options_text,
        "tags": tags_text[:300],
        "difficulty": min(max(difficulty, 1), 5),
        "citations": sorted(set(citation_numbers)),
    }


def generate_grounded_questions(
    *,
    payload: dict[str, object],
    session_factory: Callable[[], Session],
    embeddings: Embeddings,
    embedding_version: str,
    dimensions: int,
    chat_model: BaseChatModel | None,
    chat_provider: str,
    chat_model_name: str,
    reranker: Reranker | None = None,
    rerank_candidate_limit: int = 24,
    query_rewrite_enabled: bool = True,
    hybrid_retrieval_enabled: bool = True,
) -> dict[str, object]:
    """Generate tenant-scoped questions only from retrieved course evidence."""
    if chat_model is None:
        raise ValueError("AI chat model is not configured")
    tenant_id = str(payload["tenant_id"])
    course_id = int(payload["course_id"])
    request = str(payload["request"]).strip()
    count = int(payload.get("count", 5))
    difficulty = int(payload.get("difficulty", 3))
    kinds = [str(kind) for kind in payload.get("kinds", ["single_choice", "short_answer"])]
    if not request or not 1 <= count <= 20 or not 1 <= difficulty <= 5 or not set(kinds) <= ALLOWED_QUESTION_KINDS:
        raise ValueError("invalid question generation request")

    with session_factory() as session:
        set_session_tenant(session, tenant_id)
        selected_point_id = int(payload["knowledge_point_id"]) if payload.get("knowledge_point_id") is not None else None
        selected_point = session.scalar(select(KnowledgePoint).where(
            KnowledgePoint.id == selected_point_id,
            KnowledgePoint.tenant_id == tenant_id,
            KnowledgePoint.course_id == course_id,
        )) if selected_point_id is not None else None
        if selected_point_id is not None and selected_point is None:
            raise ValueError("knowledge point not found in course")
        resource_ids = [int(value) for value in payload.get("resource_ids", [])]
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
        retrieval_request = request
        if selected_point is not None:
            retrieval_request = f"{selected_point.name} {selected_point.definition[:500]} {request}".strip()
        hits = retriever.retrieve(retrieval_request, tenant_id=tenant_id, course_id=course_id, resource_ids=resource_ids or None)
        allow_ungrounded = bool(payload.get("allow_ungrounded", False))
        if not hits and not allow_ungrounded:
            raise ValueError("no indexed course evidence found; upload and index resources first")
        evidence = "\n\n".join(f"[{number}] {hit.content[:1800]}" for number, hit in enumerate(hits, start=1)) or "No course materials are indexed yet. Create a diagnostic assessment from the requested subject and level using general instructional knowledge."
        prompt = (
            ("You generate high-quality study questions from supplied evidence only. " if hits else "You generate a general baseline diagnostic assessment for the requested subject and level. ")
            + "Return JSON only, with no markdown. The JSON shape is "
            '{"questions":[{"prompt":"...","answer":"...","kind":"single_choice|multiple_choice|true_false|fill_blank|short_answer|calculation|essay|reading",'
            '"options":["..."],"explanation":"... [1]","tags":["..."],"difficulty":3,"citations":[1]}]}. '
            + ("Every question must cite one or more evidence numbers in both citations and explanation. " if hits else "No citations are required because this is an ungrounded diagnostic; clearly treat questions as a baseline assessment. ")
            + "Do not use facts that are absent from the evidence. Choice answers must exactly match one option. "
            f"Create exactly {count} questions. Requested focus: {request}. Difficulty: {difficulty}/5. "
            f"Allowed kinds: {', '.join(kinds)}.\n\nEvidence:\n{evidence}"
        )
        response = chat_model.invoke(prompt)
        input_tokens, output_tokens = response_token_usage(response)
        decoded = _json_object(response.content)
        raw_questions = decoded.get("questions")
        if not isinstance(raw_questions, list) or len(raw_questions) != count:
            raise ValueError("AI response did not contain the requested number of questions")
        questions = [_validate_question(item, len(hits), allow_ungrounded=allow_ungrounded) for item in raw_questions]

        run = AIRun(
            tenant_id=tenant_id,
            user_id=str(payload.get("user_id") or "") or None,
            run_uuid=str(uuid4()),
            feature="question_generation",
            status="completed",
            provider=chat_provider,
            model_name=chat_model_name,
            prompt_version="saas-grounded-question-generation-v1",
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_json=json.dumps({"request": request, "count": count, "difficulty": difficulty, "kinds": kinds}, ensure_ascii=False),
            output_json=json.dumps({"count": len(questions), "question_ids": [], "evidence_count": len(hits)}, ensure_ascii=False),
            course_id=course_id,
            finished_at=datetime.now(),
        )
        session.add(run)
        session.flush()
        for number, hit in enumerate(hits, start=1):
            session.add(AICitation(tenant_id=tenant_id, ai_run_id=run.id, chunk_id=hit.chunk_id, citation_number=number, quote_text=hit.content[:1000], relevance_score=hit.rrf_score))
        draft_ids = []
        question_ids = []
        auto_accept = bool(payload.get("auto_accept", False))
        knowledge_points = session.scalars(select(KnowledgePoint).where(
            KnowledgePoint.tenant_id == tenant_id, KnowledgePoint.course_id == course_id,
        ).order_by(KnowledgePoint.importance.desc(), KnowledgePoint.id)).all()
        for question_index, item in enumerate(questions, start=1):
            point = selected_point or next((candidate for candidate in knowledge_points
                          if candidate.name.casefold() in item["prompt"].casefold()), None)
            if point is None and knowledge_points:
                point = knowledge_points[len(draft_ids) % len(knowledge_points)]
            if auto_accept:
                if point is None:
                    # Give the learner an evidence-grounded concept to study
                    # before attempting this first set of generated questions.
                    label = next((tag.strip() for tag in item["tags"].split(",") if tag.strip()), "学习要点")
                    point = KnowledgePoint(
                        tenant_id=tenant_id, course_id=course_id,
                        name=f"{label[:120]} {question_index}".strip(),
                        category="概念", definition=item["explanation"][:20000],
                        difficulty=item["difficulty"], importance=3,
                    )
                    session.add(point); session.flush(); knowledge_points.append(point)
                question = Question(
                    tenant_id=tenant_id, course_id=course_id, knowledge_point_id=point.id if point else None,
                    kind=item["kind"], prompt=item["prompt"], answer=item["answer"], explanation=item["explanation"],
                    options="\n".join(json.loads(item["options"])) if item["options"] else "", tags=item["tags"],
                    difficulty=item["difficulty"], source="ai",
                )
                session.add(question); session.flush(); question_ids.append(question.id)
                continue
            draft = QuestionDraft(
                tenant_id=tenant_id, ai_run_id=run.id, course_id=course_id,
                knowledge_point_id=point.id if point else None,
                kind=item["kind"], prompt=item["prompt"], answer=item["answer"],
                explanation=item["explanation"], options_json=item["options"],
                tags_json=json.dumps([tag for tag in item["tags"].split(", ") if tag], ensure_ascii=False),
                difficulty=item["difficulty"], status="pending",
            )
            session.add(draft)
            session.flush()
            draft_ids.append(draft.id)
            for citation_number in item["citations"]:
                hit = hits[citation_number - 1]
                session.add(QuestionDraftCitation(
                    question_draft_id=draft.id, chunk_id=hit.chunk_id,
                    citation_number=citation_number, quote_text=hit.content[:1000],
                ))
        plan_job_id = None
        goal_id = payload.get("goal_id")
        if auto_accept and question_ids and goal_id:
            plan_job = BackgroundJob(
                tenant_id=tenant_id, job_type="ai_feature", status="queued",
                payload=json.dumps({"tenant_id": tenant_id, "feature": "learning_plan", "data": {
                    "goal_id": int(goal_id), "course_id": course_id,
                    "request": str(payload.get("request") or "根据已索引课程资料安排每日学习任务"),
                }}, ensure_ascii=False), detail="queued after grounded questions became available",
            )
            session.add(plan_job); session.flush(); plan_job_id = plan_job.id
        run.output_json = json.dumps({"count": len(question_ids) if auto_accept else len(draft_ids), "question_draft_ids": draft_ids, "question_ids": question_ids, "evidence_count": len(hits)}, ensure_ascii=False)
        session.commit()
        return {"ai_run_id": run.id, "question_draft_ids": draft_ids, "question_ids": question_ids, "count": len(question_ids) if auto_accept else len(draft_ids),
                "evidence_count": len(hits), "practice_session_id": None, "plan_job_id": plan_job_id,
                "review_required": not auto_accept}
