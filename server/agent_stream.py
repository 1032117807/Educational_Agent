from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime

from ai.config import get_ai_settings
from ai.gateways import create_chat_model
from app.models import AgentMessage, AgentSession, AgentToolCall, BackgroundJob, Course, Question, QuestionAttempt, StudyGoal, StudySession, StudyTask
from server.ai_services.agent import infer_actions
from server.tenant_session import set_session_tenant


def _event(name: str, data: object) -> str:
    return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


def list_sessions(db, tenant_id: str) -> list[dict[str, object]]:
    rows = db.query(AgentSession).filter(AgentSession.tenant_id == tenant_id, AgentSession.archived.is_(False)).order_by(AgentSession.updated_at.desc(), AgentSession.id.desc()).all()
    return [{"id": row.id, "title": row.title, "updated_at": row.updated_at.isoformat()} for row in rows]


def session_messages(db, tenant_id: str, session_id: int) -> list[dict[str, object]]:
    session = db.query(AgentSession).filter(AgentSession.id == session_id, AgentSession.tenant_id == tenant_id).first()
    if session is None: raise ValueError("agent session not found")
    rows = db.query(AgentMessage).filter(AgentMessage.session_id == session_id).order_by(AgentMessage.id).all()
    return [{"id": row.id, "role": row.role, "content": row.content, "created_at": row.created_at.isoformat()} for row in rows]


def learning_snapshot(db, tenant_id: str, course_id: int | None) -> dict[str, object]:
    """The agent's read-only SaaS tool for the learner's existing workspace data."""
    course_query = db.query(Course).filter(Course.tenant_id == tenant_id)
    if course_id is not None:
        course_query = course_query.filter(Course.id == course_id)
    courses = course_query.order_by(Course.id).all()
    course_ids = [item.id for item in courses]
    tasks = db.query(StudyTask).filter(StudyTask.tenant_id == tenant_id)
    attempts = db.query(QuestionAttempt).filter(QuestionAttempt.tenant_id == tenant_id)
    studies = db.query(StudySession).filter(StudySession.tenant_id == tenant_id)
    if course_ids:
        tasks = tasks.filter(StudyTask.course_id.in_(course_ids))
        studies = studies.filter(StudySession.course_id.in_(course_ids))
        attempts = attempts.join(Question, Question.id == QuestionAttempt.question_id).filter(Question.course_id.in_(course_ids))
    else:
        tasks = tasks.filter(False); attempts = attempts.filter(False); studies = studies.filter(False)
    recent_attempts = attempts.order_by(QuestionAttempt.attempted_at.desc()).limit(20).all()
    wrong = [item for item in recent_attempts if item.correct is False]
    goals = db.query(StudyGoal).filter(StudyGoal.tenant_id == tenant_id)
    if course_id is not None: goals = goals.filter(StudyGoal.course_id == course_id)
    return {
        "courses": [{"id": item.id, "name": item.name, "progress": item.progress} for item in courses],
        "goals": [{"id": item.id, "title": item.title, "target_date": item.target_date.isoformat(), "weekly_minutes": item.weekly_minutes, "progress": item.progress} for item in goals.order_by(StudyGoal.target_date).limit(10)],
        "study_minutes": sum(item.duration_minutes for item in studies.all()),
        "tasks": {"total": tasks.count(), "completed": tasks.filter(StudyTask.completed.is_(True)).count()},
        "practice": {"recent_attempts": len(recent_attempts), "correct": sum(item.correct is True for item in recent_attempts), "wrong_question_ids": [item.question_id for item in wrong]},
    }


def stream_agent_reply(*, session_factory, tenant_id: str, user_id: str, session_id: int, message: str, course_id: int | None) -> Iterator[str]:
    """Persist a conversation and stream text before durable tool execution starts."""
    with session_factory() as db:
        set_session_tenant(db, tenant_id)
        session = db.query(AgentSession).filter(AgentSession.id == session_id, AgentSession.tenant_id == tenant_id).first()
        if session is None: raise ValueError("agent session not found")
        db.add(AgentMessage(session_id=session_id, role="user", content=message))
        if session.title == "New session": session.title = message.strip()[:80]
        session.updated_at = datetime.now()
        db.commit()
    yield _event("status", {"state": "thinking"})
    actions = infer_actions(message)
    yield _event("intent", {"actions": actions})
    with session_factory() as db:
        set_session_tenant(db, tenant_id)
        snapshot = learning_snapshot(db, tenant_id, course_id)
        db.add(AgentToolCall(session_id=session_id, tool_name="learning_data.read_snapshot", status="completed", detail="read current tenant learning records", input_json=json.dumps({"course_id": course_id}, ensure_ascii=False), output_json=json.dumps(snapshot, ensure_ascii=False), finished_at=datetime.now()))
        db.commit()
    yield _event("tool", {"name": "learning_data.read_snapshot", "state": "completed", "summary": {"courses": len(snapshot["courses"]), "study_minutes": snapshot["study_minutes"], "recent_attempts": snapshot["practice"]["recent_attempts"]}})
    settings = get_ai_settings()
    if not settings.enabled or not settings.api_key.strip():
        reply = "AI 模型尚未配置。请设置 LEARNING_AI_ENABLED=true 和 LEARNING_AI_API_KEY 后重试。"
        yield _event("token", {"text": reply})
    else:
        model = create_chat_model(settings)
        prompt = (
            "You are a Chinese learning agent. Respond naturally in Chinese. "
            "Use the supplied workspace snapshot as the source of truth. Do not ask the learner to repeat data already in it. "
            "First state your intent understanding, cite concrete available counts when relevant, then explain the next actions. "
            "Do not claim that a queued tool action is completed.\n"
            f"Planned actions: {', '.join(actions)}.\nWorkspace snapshot: {json.dumps(snapshot, ensure_ascii=False)}\nLearner message: {message}"
        )
        reply_parts: list[str] = []
        for chunk in model.stream(prompt):
            content = chunk.content if isinstance(chunk.content, str) else str(chunk.content)
            if content:
                reply_parts.append(content)
                yield _event("token", {"text": content})
        reply = "".join(reply_parts).strip() or "我已理解你的请求，正在准备执行。"
    with session_factory() as db:
        set_session_tenant(db, tenant_id)
        db.add(AgentMessage(session_id=session_id, role="assistant", content=reply))
        db.add(AgentToolCall(session_id=session_id, tool_name="intent_router", status="completed", detail="planned: " + ", ".join(actions), input_json=json.dumps({"message": message}, ensure_ascii=False), output_json=json.dumps({"actions": actions}, ensure_ascii=False), finished_at=datetime.now()))
        job = BackgroundJob(tenant_id=tenant_id, requested_by=user_id, job_type="learning_agent", status="queued", payload=json.dumps({"tenant_id": tenant_id, "data": {"message": message, "course_id": course_id}}, ensure_ascii=False), detail="queued by streaming agent")
        db.add(job); db.commit(); db.refresh(job)
    yield _event("tool", {"actions": actions, "job_id": job.id, "state": "queued"})
    yield _event("done", {"session_id": session_id})
