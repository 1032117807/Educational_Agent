from __future__ import annotations

from collections.abc import Callable

from langchain_core.embeddings import Embeddings
from langchain_core.language_models.chat_models import BaseChatModel
from sqlalchemy.orm import Session

from server.ai_services.orchestration import run_ai_feature
from server.question_generation_worker import generate_grounded_questions


def infer_actions(message: str) -> list[str]:
    """Conservative intent router for the autonomous learning supervisor."""
    value = message.lower()
    actions: list[str] = []
    rules = (
        ("knowledge_extraction", ("知识点", "提取", "分析资料")),
        ("subjective_grading", ("批改", "评分", "主观题", "简答题")),
        ("error_analysis", ("错因", "错题", "错误分析", "错在哪里")),
        ("learning_plan", ("计划", "安排", "复习", "怎么学")),
        ("learning_report", ("报告", "总结", "本周表现")),
        ("research_curation", ("研究", "查资料", "资料推荐")),
        ("generate_questions", ("出题", "题目", "练习题", "出", "练习")),
    )
    for action, terms in rules:
        if any(term in value for term in terms):
            actions.append(action)
    return actions or ["agent_chat"]


def run_learning_agent(*, payload: dict[str, object], session_factory: Callable[[], Session], embeddings: Embeddings, embedding_version: str, dimensions: int, chat_model: BaseChatModel | None, provider: str, model_name: str) -> dict[str, object]:
    """Execute the desktop-style supervisor plan within one tenant boundary."""
    tenant_id = str(payload["tenant_id"])
    data = payload.get("data", {})
    if not isinstance(data, dict):
        raise ValueError("agent input must be an object")
    message = str(data.get("message", "")).strip()
    if not message:
        raise ValueError("message is required")
    actions = infer_actions(message)
    completed: list[dict[str, object]] = []
    for action in actions:
        if action == "generate_questions":
            course_id = data.get("course_id")
            if course_id is None:
                completed.append({"feature": action, "status": "needs_input", "detail": "Select a course before the agent can generate grounded questions."})
                continue
            result = generate_grounded_questions(
                payload={"tenant_id": tenant_id, "course_id": int(course_id), "request": message, "count": 5, "difficulty": 3, "kinds": ["single_choice", "short_answer"]},
                session_factory=session_factory, embeddings=embeddings, embedding_version=embedding_version,
                dimensions=dimensions, chat_model=chat_model, chat_provider=provider, chat_model_name=model_name,
            )
            completed.append({"feature": action, "status": "completed", "result": result})
            continue
        feature_data = dict(data)
        feature_data["request"] = message
        feature_data.pop("message", None)
        try:
            result = run_ai_feature(
                payload={"tenant_id": tenant_id, "feature": action, "data": feature_data},
                session_factory=session_factory, embeddings=embeddings, embedding_version=embedding_version,
                dimensions=dimensions, chat_model=chat_model, provider=provider, model_name=model_name,
            )
            completed.append({"feature": action, "status": "completed", "result": result})
        except Exception as exc:
            completed.append({"feature": action, "status": "needs_input", "detail": str(exc)})
    return {"message": message, "planned_actions": actions, "actions": completed}
