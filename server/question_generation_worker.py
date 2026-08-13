from __future__ import annotations

import json
import re
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.orm import Session

from app.models import AICitation, AIRun, Question
from server.rag_retriever import TenantPgVectorRetriever
from server.tenant_session import set_session_tenant


ALLOWED_QUESTION_KINDS = {"single_choice", "multiple_choice", "true_false", "short_answer"}


def _json_object(content: object) -> dict[str, object]:
    text = content if isinstance(content, str) else str(content)
    text = re.sub(r"^\s*```(?:json)?\s*|\s*```\s*$", "", text, flags=re.IGNORECASE)
    decoded = json.loads(text)
    if not isinstance(decoded, dict):
        raise ValueError("AI response must be a JSON object")
    return decoded


def _validate_question(item: object, evidence_count: int) -> dict[str, object]:
    if not isinstance(item, dict):
        raise ValueError("each generated question must be an object")
    prompt = str(item.get("prompt", "")).strip()
    answer = str(item.get("answer", "")).strip()
    kind = str(item.get("kind", "")).strip()
    explanation = str(item.get("explanation", "")).strip()
    citations = item.get("citations", [])
    if not prompt or not answer or kind not in ALLOWED_QUESTION_KINDS:
        raise ValueError("generated question has missing or unsupported fields")
    if not isinstance(citations, list) or not citations:
        raise ValueError("every generated question requires evidence citations")
    citation_numbers = [int(value) for value in citations]
    if any(number < 1 or number > evidence_count for number in citation_numbers):
        raise ValueError("generated question cites evidence outside the retrieved set")
    if not all(f"[{number}]" in explanation for number in citation_numbers):
        raise ValueError("question explanation must include its evidence citations")
    options = item.get("options", [])
    if kind in {"single_choice", "multiple_choice"}:
        if not isinstance(options, list) or len(options) < 2:
            raise ValueError("choice questions require at least two options")
        options_text = json.dumps([str(option) for option in options], ensure_ascii=False)
    else:
        options_text = ""
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
        retriever = TenantPgVectorRetriever(
            session=session,
            embeddings=embeddings,
            embedding_version=embedding_version,
            dimensions=dimensions,
        )
        hits = retriever.retrieve(request, tenant_id=tenant_id, course_id=course_id)
        if not hits:
            raise ValueError("no indexed course evidence found; upload and index resources first")
        evidence = "\n\n".join(f"[{number}] {hit.content[:1800]}" for number, hit in enumerate(hits, start=1))
        prompt = (
            "You generate high-quality study questions from supplied evidence only. "
            "Return JSON only, with no markdown. The JSON shape is "
            '{"questions":[{"prompt":"...","answer":"...","kind":"single_choice|multiple_choice|true_false|short_answer",'
            '"options":["..."],"explanation":"... [1]","tags":["..."],"difficulty":3,"citations":[1]}]}. '
            "Every question must cite one or more evidence numbers in both citations and explanation. "
            "Do not use facts that are absent from the evidence. Choice answers must exactly match one option. "
            f"Create exactly {count} questions. Requested focus: {request}. Difficulty: {difficulty}/5. "
            f"Allowed kinds: {', '.join(kinds)}.\n\nEvidence:\n{evidence}"
        )
        response = chat_model.invoke(prompt)
        decoded = _json_object(response.content)
        raw_questions = decoded.get("questions")
        if not isinstance(raw_questions, list) or len(raw_questions) != count:
            raise ValueError("AI response did not contain the requested number of questions")
        questions = [_validate_question(item, len(hits)) for item in raw_questions]

        run = AIRun(
            tenant_id=tenant_id,
            run_uuid=str(uuid4()),
            feature="question_generation",
            status="completed",
            provider=chat_provider,
            model_name=chat_model_name,
            prompt_version="saas-grounded-question-generation-v1",
            input_json=json.dumps({"request": request, "count": count, "difficulty": difficulty, "kinds": kinds}, ensure_ascii=False),
            output_json=json.dumps({"count": len(questions), "question_ids": [], "evidence_count": len(hits)}, ensure_ascii=False),
            course_id=course_id,
            finished_at=datetime.now(),
        )
        session.add(run)
        session.flush()
        for number, hit in enumerate(hits, start=1):
            session.add(AICitation(tenant_id=tenant_id, ai_run_id=run.id, chunk_id=hit.chunk_id, citation_number=number, quote_text=hit.content[:1000], relevance_score=hit.rrf_score))
        persisted = []
        for item in questions:
            question = Question(tenant_id=tenant_id, course_id=course_id, **{key: value for key, value in item.items() if key != "citations"})
            session.add(question)
            session.flush()
            persisted.append(question.id)
        run.output_json = json.dumps({"count": len(persisted), "question_ids": persisted, "evidence_count": len(hits)}, ensure_ascii=False)
        session.commit()
        return {"ai_run_id": run.id, "question_ids": persisted, "count": len(persisted), "evidence_count": len(hits)}
