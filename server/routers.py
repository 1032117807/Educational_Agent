from __future__ import annotations
from uuid import uuid4
import hashlib
import json
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from app.models import (
    BackgroundJob,
    AICitation,
    AIRun,
    AuditEvent,
    Course,
    KnowledgePoint,
    Organization,
    OrganizationMember,
    PracticeSession,
    PracticeSessionQuestion,
    Question,
    QuestionAttempt,
    RefreshToken,
    ReviewAttempt,
    ReviewItem,
    ResourceFile,
    StudyGoal,
    StudySession,
    StudyTask,
    User,
)
from server.config import get_server_settings
from server.deps import CurrentContext, DbSession, require_org_admin
from datetime import date, datetime, timedelta
from server.security import create_access_token, create_refresh_token, hash_password, hash_refresh_token, verify_password
from server.storage import S3ObjectStorage, resource_key
from server.agent_stream import list_sessions, session_messages, stream_agent_reply
from server.db import session_factory
from app.agent_runtime import tools_for_client

router = APIRouter(prefix="/v1")
class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=10, max_length=200)
    organization_name: str = Field(min_length=1, max_length=160)
    display_name: str = Field(default="", max_length=160)
class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str
class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=200)
class CourseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=10000)
    subject: str = Field(default="其他", max_length=60)


class OrganizationMemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    role: str = Field(default="member", pattern="^(admin|member)$")


class OrganizationMemberRoleRequest(BaseModel):
    role: str = Field(pattern="^(admin|member)$")


class TaskRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    duration_minutes: int = Field(default=30, ge=1, le=1440)
    planned_date: date | None = None
    priority: str = Field(default="medium", max_length=20)
    scheduled_time: str = Field(default="", max_length=5)
    note: str = Field(default="", max_length=10000)
    course_id: int | None = None


class QuestionRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    answer: str = Field(min_length=1, max_length=20000)
    kind: str = Field(default="single_choice", max_length=20)
    explanation: str = Field(default="", max_length=20000)
    options: str = Field(default="", max_length=20000)
    tags: str = Field(default="", max_length=300)
    difficulty: int = Field(default=3, ge=1, le=5)
    course_id: int | None = None


class GoalRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    target_date: date
    target_score: float | None = Field(default=None, ge=0, le=1000)
    weekly_minutes: int = Field(default=420, ge=1, le=10080)
    course_id: int | None = None


class KnowledgePointRequest(BaseModel):
    course_id: int
    name: str = Field(min_length=1, max_length=160)
    category: str = Field(default="concept", max_length=30)
    definition: str = Field(default="", max_length=20000)
    note: str = Field(default="", max_length=20000)
    difficulty: int = Field(default=3, ge=1, le=5)
    importance: int = Field(default=3, ge=1, le=5)


class PracticeStartRequest(BaseModel):
    question_ids: list[int] = Field(min_length=1, max_length=100)
    course_id: int | None = None


class PracticeAttemptRequest(BaseModel):
    response: str = Field(default="", max_length=20000)
    elapsed_seconds: int = Field(default=0, ge=0, le=86400)


class ReviewRequest(BaseModel):
    result: str = Field(pattern="^(correct|wrong|mastered|postpone)$")


class StudySessionRequest(BaseModel):
    course_id: int | None = None
    task_id: int | None = None
    note: str = Field(default="", max_length=10000)


class StudySessionFinishRequest(BaseModel):
    duration_minutes: int = Field(ge=0, le=1440)
    note: str | None = Field(default=None, max_length=10000)


class RagRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    course_id: int | None = None


class AiQuestionGenerationRequest(BaseModel):
    course_id: int
    request: str = Field(min_length=1, max_length=4000)
    count: int = Field(default=5, ge=1, le=20)
    difficulty: int = Field(default=3, ge=1, le=5)
    kinds: list[str] = Field(default_factory=lambda: ["single_choice", "short_answer"], min_length=1, max_length=4)


class AiFeatureRequest(BaseModel):
    feature: str = Field(pattern="^(knowledge_extraction|subjective_grading|error_analysis|learning_plan|learning_report|research_curation|agent_chat)$")
    course_id: int | None = None
    attempt_id: int | None = None
    goal_id: int | None = None
    request: str = Field(default="", max_length=4000)
    max_score: float = Field(default=100, gt=0, le=1000)
    start_date: date | None = None
    end_date: date | None = None


class AgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    course_id: int | None = None
    attempt_id: int | None = None
    goal_id: int | None = None


class AgentSessionRequest(BaseModel):
    title: str = Field(default="New session", min_length=1, max_length=160)


class AgentMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    course_id: int | None = None


def record_audit(
    db: DbSession,
    context: CurrentContext,
    action: str,
    target_type: str = "",
    target_id: str = "",
    detail: dict[str, object] | None = None,
) -> None:
    db.add(AuditEvent(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        action=action,
        target_type=target_type,
        target_id=target_id,
        detail=json.dumps(detail or {}, ensure_ascii=False),
    ))
@router.post("/auth/register", status_code=status.HTTP_201_CREATED)
def register(payload: RegisterRequest, db: DbSession) -> dict[str, str]:
    email = str(payload.email).lower()
    if db.scalar(select(User).where(User.email == email)): raise HTTPException(status_code=409, detail="email already registered")
    user_id, organization_id = str(uuid4()), str(uuid4())
    db.add_all([
        Organization(id=organization_id, name=payload.organization_name, slug=f"org-{organization_id[:8]}"),
        User(id=user_id, email=email, password_hash=hash_password(payload.password), display_name=payload.display_name),
    ])
    # The membership has foreign keys to both records. Flush them before
    # creating it so PostgreSQL cannot choose an invalid insert order.
    db.flush()
    db.add(OrganizationMember(organization_id=organization_id, user_id=user_id, role="owner"))
    refresh_raw, refresh_digest = create_refresh_token()
    db.add(RefreshToken(id=str(uuid4()), user_id=user_id, token_hash=refresh_digest, expires_at=datetime.now() + timedelta(days=get_server_settings().refresh_token_days)))
    db.commit()
    return {"access_token": create_access_token(user_id=user_id, organization_id=organization_id, settings=get_server_settings()), "refresh_token": refresh_raw, "token_type": "bearer"}
@router.post("/auth/login")
def login(payload: LoginRequest, db: DbSession) -> dict[str, str]:
    user = db.scalar(select(User).where(User.email == str(payload.email).lower(), User.is_active.is_(True)))
    if user is None or not verify_password(payload.password, user.password_hash): raise HTTPException(status_code=401, detail="invalid credentials")
    membership = db.scalar(select(OrganizationMember).where(OrganizationMember.user_id == user.id).order_by(OrganizationMember.created_at))
    if membership is None: raise HTTPException(status_code=403, detail="user has no organization")
    refresh_raw, refresh_digest = create_refresh_token()
    db.add(RefreshToken(id=str(uuid4()), user_id=user.id, token_hash=refresh_digest, expires_at=datetime.now() + timedelta(days=get_server_settings().refresh_token_days)))
    db.commit()
    return {"access_token": create_access_token(user_id=user.id, organization_id=membership.organization_id, settings=get_server_settings()), "refresh_token": refresh_raw, "token_type": "bearer"}


@router.post("/auth/refresh")
def refresh(payload: RefreshRequest, db: DbSession) -> dict[str, str]:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(payload.refresh_token), RefreshToken.revoked_at.is_(None)))
    if token is None or token.expires_at <= datetime.now():
        raise HTTPException(status_code=401, detail="invalid refresh token")
    user = db.get(User, token.user_id)
    member = db.scalar(select(OrganizationMember).where(OrganizationMember.user_id == token.user_id).order_by(OrganizationMember.created_at))
    if user is None or not user.is_active or member is None:
        raise HTTPException(status_code=401, detail="user is inactive")
    token.revoked_at = datetime.now()
    refresh_raw, refresh_digest = create_refresh_token()
    db.add(RefreshToken(id=str(uuid4()), user_id=user.id, token_hash=refresh_digest, expires_at=datetime.now() + timedelta(days=get_server_settings().refresh_token_days)))
    db.commit()
    return {"access_token": create_access_token(user_id=user.id, organization_id=member.organization_id, settings=get_server_settings()), "refresh_token": refresh_raw, "token_type": "bearer"}


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(payload: RefreshRequest, db: DbSession) -> None:
    token = db.scalar(select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(payload.refresh_token), RefreshToken.revoked_at.is_(None)))
    if token is not None:
        token.revoked_at = datetime.now()
        db.commit()
@router.get("/me")
def me(context: CurrentContext, db: DbSession) -> dict[str, str]:
    user = db.get(User, context.user_id)
    if user is None: raise HTTPException(status_code=404, detail="user not found")
    return {"id": user.id, "email": user.email, "tenant_id": context.tenant_id, "display_name": user.display_name, "role": context.role}


@router.get("/organization/members")
def list_organization_members(context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    rows = db.execute(
        select(OrganizationMember, User)
        .join(User, User.id == OrganizationMember.user_id)
        .where(OrganizationMember.organization_id == context.tenant_id)
        .order_by(OrganizationMember.created_at, OrganizationMember.id)
    ).all()
    return [{
        "user_id": member.user_id,
        "email": user.email,
        "display_name": user.display_name,
        "role": member.role,
        "created_at": member.created_at.isoformat(),
    } for member, user in rows]


@router.post("/organization/members", status_code=status.HTTP_201_CREATED)
def add_organization_member(
    payload: OrganizationMemberRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    require_org_admin(context)
    email = payload.email.strip().lower()
    user = db.scalar(select(User).where(User.email == email, User.is_active.is_(True)))
    if user is None:
        raise HTTPException(status_code=404, detail="user not found; registration is required before invitation")
    existing = db.scalar(select(OrganizationMember).where(
        OrganizationMember.organization_id == context.tenant_id,
        OrganizationMember.user_id == user.id,
    ))
    if existing is not None:
        raise HTTPException(status_code=409, detail="user is already a member")
    member = OrganizationMember(organization_id=context.tenant_id, user_id=user.id, role=payload.role)
    db.add(member)
    db.flush()
    record_audit(db, context, "organization.member_add", "user", user.id, {"role": payload.role})
    db.commit()
    return {"user_id": user.id, "email": user.email, "role": member.role}


@router.patch("/organization/members/{user_id}")
def update_organization_member(
    user_id: str, payload: OrganizationMemberRoleRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    require_org_admin(context)
    member = db.scalar(select(OrganizationMember).where(
        OrganizationMember.organization_id == context.tenant_id,
        OrganizationMember.user_id == user_id,
    ))
    if member is None:
        raise HTTPException(status_code=404, detail="organization member not found")
    if member.role == "owner":
        raise HTTPException(status_code=409, detail="owner role cannot be changed")
    member.role = payload.role
    record_audit(db, context, "organization.member_role_update", "user", user_id, {"role": payload.role})
    db.commit()
    return {"user_id": user_id, "role": member.role}


@router.delete("/organization/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_organization_member(user_id: str, context: CurrentContext, db: DbSession) -> None:
    require_org_admin(context)
    if user_id == context.user_id:
        raise HTTPException(status_code=409, detail="you cannot remove yourself from the organization")
    member = db.scalar(select(OrganizationMember).where(
        OrganizationMember.organization_id == context.tenant_id,
        OrganizationMember.user_id == user_id,
    ))
    if member is None:
        raise HTTPException(status_code=404, detail="organization member not found")
    if member.role == "owner":
        raise HTTPException(status_code=409, detail="owner membership cannot be removed")
    record_audit(db, context, "organization.member_remove", "user", user_id, {"role": member.role})
    db.delete(member)
    db.commit()


@router.get("/dashboard")
def dashboard(
    context: CurrentContext,
    db: DbSession,
    start: date | None = None,
    end: date | None = None,
    course_id: int | None = None,
) -> dict[str, object]:
    end_date = end or date.today()
    start_date = start or end_date - timedelta(days=6)
    if end_date < start_date or (end_date - start_date).days > 90:
        raise HTTPException(status_code=422, detail="date range must be between 0 and 90 days")
    if course_id is not None and db.scalar(
        select(Course.id).where(Course.id == course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")

    start_at = datetime.combine(start_date, datetime.min.time())
    end_at = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    task_statement = select(StudyTask).where(
        StudyTask.tenant_id == context.tenant_id,
        StudyTask.planned_date >= start_date,
        StudyTask.planned_date <= end_date,
    )
    study_statement = select(StudySession).where(
        StudySession.tenant_id == context.tenant_id,
        StudySession.started_at >= start_at,
        StudySession.started_at < end_at,
    )
    practice_statement = select(PracticeSession).where(
        PracticeSession.tenant_id == context.tenant_id,
        PracticeSession.started_at >= start_at,
        PracticeSession.started_at < end_at,
        PracticeSession.status == "completed",
    )
    if course_id is not None:
        task_statement = task_statement.where(StudyTask.course_id == course_id)
        study_statement = study_statement.where(StudySession.course_id == course_id)
        practice_statement = practice_statement.where(PracticeSession.course_id == course_id)

    tasks = db.scalars(task_statement).all()
    studies = db.scalars(study_statement).all()
    practices = db.scalars(practice_statement).all()
    review_count = db.scalar(
        select(func.count()).select_from(ReviewAttempt).where(
            ReviewAttempt.tenant_id == context.tenant_id,
            ReviewAttempt.created_at >= start_at,
            ReviewAttempt.created_at < end_at,
        )
    ) or 0
    due_reviews = db.scalar(
        select(func.count()).select_from(ReviewItem).where(
            ReviewItem.tenant_id == context.tenant_id,
            ReviewItem.status.not_in(("archived", "mastered")),
            ReviewItem.next_review <= end_date,
        )
    ) or 0
    daily = {start_date + timedelta(days=offset): 0 for offset in range((end_date - start_date).days + 1)}
    for study in studies:
        daily[study.started_at.date()] = daily.get(study.started_at.date(), 0) + study.duration_minutes
    question_total = sum(practice.total for practice in practices)
    question_correct = sum(practice.correct for practice in practices)
    return {
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat()},
        "course_id": course_id,
        "study_minutes": sum(study.duration_minutes for study in studies),
        "tasks": {"total": len(tasks), "completed": sum(task.completed for task in tasks)},
        "practice": {
            "questions": question_total,
            "correct": question_correct,
            "accuracy": round(question_correct * 100 / question_total, 1) if question_total else 0.0,
        },
        "reviews": {"completed": review_count, "due": due_reviews},
        "daily_study_minutes": [{"date": day.isoformat(), "minutes": minutes} for day, minutes in daily.items()],
    }


@router.get("/audit-events")
def list_audit_events(
    context: CurrentContext, db: DbSession, limit: int = 100
) -> list[dict[str, object]]:
    bounded_limit = min(max(limit, 1), 500)
    rows = db.scalars(
        select(AuditEvent)
        .where(AuditEvent.tenant_id == context.tenant_id)
        .order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
        .limit(bounded_limit)
    ).all()
    return [{
        "id": row.id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": row.target_id,
        "detail": json.loads(row.detail or "{}"),
        "created_at": row.created_at.isoformat(),
    } for row in rows]


@router.get("/courses")
def list_courses(context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    rows = db.scalars(select(Course).where(Course.tenant_id == context.tenant_id).order_by(Course.id)).all()
    return [{"id": row.id, "name": row.name, "description": row.description, "subject": row.subject} for row in rows]


@router.post("/courses", status_code=status.HTTP_201_CREATED)
def create_course(payload: CourseRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    course = Course(tenant_id=context.tenant_id, name=payload.name, description=payload.description, subject=payload.subject)
    db.add(course)
    db.flush()
    record_audit(db, context, "course.create", "course", str(course.id), {"name": course.name})
    db.commit()
    db.refresh(course)
    return {"id": course.id, "name": course.name, "tenant_id": context.tenant_id}


@router.get("/tasks")
def list_tasks(
    context: CurrentContext,
    db: DbSession,
    start: date | None = None,
    end: date | None = None,
) -> list[dict[str, object]]:
    statement = select(StudyTask).where(StudyTask.tenant_id == context.tenant_id)
    if start is not None:
        statement = statement.where(StudyTask.planned_date >= start)
    if end is not None:
        statement = statement.where(StudyTask.planned_date <= end)
    rows = db.scalars(statement.order_by(StudyTask.planned_date, StudyTask.id)).all()
    return [{
        "id": row.id,
        "title": row.title,
        "course_id": row.course_id,
        "planned_date": row.planned_date.isoformat(),
        "duration_minutes": row.duration_minutes,
        "priority": row.priority,
        "completed": row.completed,
    } for row in rows]


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    if payload.course_id is not None and db.scalar(
        select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")
    task = StudyTask(
        tenant_id=context.tenant_id,
        title=payload.title.strip(),
        duration_minutes=payload.duration_minutes,
        planned_date=payload.planned_date or date.today(),
        priority=payload.priority,
        scheduled_time=payload.scheduled_time,
        note=payload.note,
        course_id=payload.course_id,
    )
    db.add(task)
    db.flush()
    record_audit(db, context, "task.create", "study_task", str(task.id), {"title": task.title})
    db.commit()
    db.refresh(task)
    return {"id": task.id, "title": task.title, "tenant_id": context.tenant_id}


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: int, context: CurrentContext, db: DbSession) -> dict[str, object]:
    task = db.scalar(select(StudyTask).where(StudyTask.id == task_id, StudyTask.tenant_id == context.tenant_id))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    if not task.completed:
        task.completed = True
        task.completed_at = datetime.now()
        record_audit(db, context, "task.complete", "study_task", str(task.id))
        db.commit()
    return {"id": task.id, "completed": task.completed}


@router.get("/questions")
def list_questions(context: CurrentContext, db: DbSession, course_id: int | None = None) -> list[dict[str, object]]:
    statement = select(Question).where(Question.tenant_id == context.tenant_id, Question.archived.is_(False))
    if course_id is not None:
        statement = statement.where(Question.course_id == course_id)
    rows = db.scalars(statement.order_by(Question.id.desc())).all()
    return [{
        "id": row.id,
        "prompt": row.prompt,
        "answer": row.answer,
        "kind": row.kind,
        "course_id": row.course_id,
        "difficulty": row.difficulty,
        "tags": row.tags,
    } for row in rows]


@router.post("/questions", status_code=status.HTTP_201_CREATED)
def create_question(payload: QuestionRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    if payload.course_id is not None and db.scalar(
        select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")
    question = Question(
        tenant_id=context.tenant_id,
        prompt=payload.prompt.strip(),
        answer=payload.answer.strip(),
        kind=payload.kind,
        explanation=payload.explanation,
        options=payload.options,
        tags=payload.tags,
        difficulty=payload.difficulty,
        course_id=payload.course_id,
    )
    db.add(question)
    db.flush()
    record_audit(db, context, "question.create", "question", str(question.id))
    db.commit()
    db.refresh(question)
    return {"id": question.id, "course_id": question.course_id, "tenant_id": context.tenant_id}


@router.get("/goals")
def list_goals(context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    rows = db.scalars(
        select(StudyGoal)
        .where(StudyGoal.tenant_id == context.tenant_id)
        .order_by(StudyGoal.target_date, StudyGoal.id)
    ).all()
    return [{
        "id": row.id,
        "title": row.title,
        "course_id": row.course_id,
        "target_date": row.target_date.isoformat(),
        "target_score": row.target_score,
        "weekly_minutes": row.weekly_minutes,
        "progress": row.progress,
        "status": row.status,
    } for row in rows]


@router.post("/goals", status_code=status.HTTP_201_CREATED)
def create_goal(payload: GoalRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    if payload.course_id is not None and db.scalar(
        select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")
    goal = StudyGoal(
        tenant_id=context.tenant_id,
        title=payload.title.strip(),
        target_date=payload.target_date,
        target_score=payload.target_score,
        weekly_minutes=payload.weekly_minutes,
        course_id=payload.course_id,
    )
    db.add(goal)
    db.flush()
    record_audit(db, context, "goal.create", "study_goal", str(goal.id))
    db.commit()
    db.refresh(goal)
    return {"id": goal.id, "tenant_id": context.tenant_id, "target_date": goal.target_date.isoformat()}


@router.get("/knowledge-points")
def list_knowledge_points(
    context: CurrentContext, db: DbSession, course_id: int | None = None
) -> list[dict[str, object]]:
    statement = select(KnowledgePoint).where(KnowledgePoint.tenant_id == context.tenant_id)
    if course_id is not None:
        statement = statement.where(KnowledgePoint.course_id == course_id)
    rows = db.scalars(statement.order_by(KnowledgePoint.course_id, KnowledgePoint.id)).all()
    return [{
        "id": row.id,
        "course_id": row.course_id,
        "name": row.name,
        "mastery": row.mastery,
        "category": row.category,
        "difficulty": row.difficulty,
        "importance": row.importance,
    } for row in rows]


@router.post("/knowledge-points", status_code=status.HTTP_201_CREATED)
def create_knowledge_point(
    payload: KnowledgePointRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    if db.scalar(
        select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")
    point = KnowledgePoint(
        tenant_id=context.tenant_id,
        course_id=payload.course_id,
        name=payload.name.strip(),
        category=payload.category,
        definition=payload.definition,
        note=payload.note,
        difficulty=payload.difficulty,
        importance=payload.importance,
    )
    db.add(point)
    db.flush()
    record_audit(db, context, "knowledge_point.create", "knowledge_point", str(point.id))
    db.commit()
    db.refresh(point)
    return {"id": point.id, "course_id": point.course_id, "tenant_id": context.tenant_id}


@router.post("/practice-sessions", status_code=status.HTTP_201_CREATED)
def start_practice_session(
    payload: PracticeStartRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    question_ids = list(dict.fromkeys(payload.question_ids))
    questions = db.scalars(
        select(Question).where(
            Question.id.in_(question_ids),
            Question.tenant_id == context.tenant_id,
            Question.archived.is_(False),
        )
    ).all()
    if len(questions) != len(question_ids):
        raise HTTPException(status_code=404, detail="one or more questions not found")
    if payload.course_id is not None and db.scalar(
        select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")
    if payload.course_id is not None and any(question.course_id != payload.course_id for question in questions):
        raise HTTPException(status_code=422, detail="questions must belong to the requested course")
    session = PracticeSession(tenant_id=context.tenant_id, course_id=payload.course_id, total=len(question_ids))
    db.add(session)
    db.flush()
    db.add_all([
        PracticeSessionQuestion(
            tenant_id=context.tenant_id,
            session_id=session.id,
            question_id=question_id,
            position=position,
        )
        for position, question_id in enumerate(question_ids, start=1)
    ])
    # The audit event is committed with the practice session and associations.
    record_audit(db, context, "practice_session.create", "practice_session", str(session.id))
    db.commit()
    return {"id": session.id, "total": session.total, "status": session.status}


@router.post("/practice-sessions/{session_id}/questions/{question_id}/attempts", status_code=status.HTTP_201_CREATED)
def submit_practice_attempt(
    session_id: int, question_id: int, payload: PracticeAttemptRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    session = db.scalar(
        select(PracticeSession).where(PracticeSession.id == session_id, PracticeSession.tenant_id == context.tenant_id)
    )
    if session is None:
        raise HTTPException(status_code=404, detail="practice session not found")
    if session.status != "running":
        raise HTTPException(status_code=409, detail="practice session is not running")
    question = db.scalar(
        select(Question).where(Question.id == question_id, Question.tenant_id == context.tenant_id)
    )
    linked = db.scalar(
        select(PracticeSessionQuestion.id).where(
            PracticeSessionQuestion.session_id == session_id,
            PracticeSessionQuestion.question_id == question_id,
            PracticeSessionQuestion.tenant_id == context.tenant_id,
        )
    )
    if question is None or linked is None:
        raise HTTPException(status_code=404, detail="question not found in practice session")
    previous = db.scalar(
        select(QuestionAttempt).where(
            QuestionAttempt.session_id == session_id,
            QuestionAttempt.question_id == question_id,
            QuestionAttempt.tenant_id == context.tenant_id,
        )
    )
    correct = payload.response.strip() == question.answer.strip()
    if previous is None:
        attempt = QuestionAttempt(
            tenant_id=context.tenant_id,
            session_id=session_id,
            question_id=question_id,
            response=payload.response,
            correct=correct,
            elapsed_seconds=payload.elapsed_seconds,
        )
        db.add(attempt)
    else:
        previous.response = payload.response
        previous.correct = correct
        previous.elapsed_seconds = payload.elapsed_seconds
        attempt = previous
    db.commit()
    record_audit(db, context, "practice_attempt.submit", "question", str(question_id), {"correct": correct})
    db.commit()
    return {"id": attempt.id, "question_id": question_id, "correct": correct}


@router.post("/practice-sessions/{session_id}/complete")
def complete_practice_session(session_id: int, context: CurrentContext, db: DbSession) -> dict[str, object]:
    session = db.scalar(
        select(PracticeSession).where(PracticeSession.id == session_id, PracticeSession.tenant_id == context.tenant_id)
    )
    if session is None:
        raise HTTPException(status_code=404, detail="practice session not found")
    attempts = db.scalars(
        select(QuestionAttempt).where(
            QuestionAttempt.session_id == session_id,
            QuestionAttempt.tenant_id == context.tenant_id,
        )
    ).all()
    session.correct = sum(1 for attempt in attempts if attempt.correct)
    session.duration_seconds = sum(attempt.elapsed_seconds for attempt in attempts)
    session.finished_at = datetime.now()
    session.status = "completed"
    record_audit(db, context, "practice_session.complete", "practice_session", str(session.id), {"correct": session.correct})
    db.commit()
    return {"id": session.id, "status": session.status, "total": session.total, "correct": session.correct}


@router.get("/reviews")
def list_reviews(context: CurrentContext, db: DbSession, due_only: bool = False) -> list[dict[str, object]]:
    statement = select(ReviewItem).where(ReviewItem.tenant_id == context.tenant_id, ReviewItem.status != "archived")
    if due_only:
        statement = statement.where(ReviewItem.next_review <= date.today(), ReviewItem.status != "mastered")
    rows = db.scalars(statement.order_by(ReviewItem.next_review, ReviewItem.id)).all()
    return [{
        "id": row.id,
        "question_id": row.question_id,
        "title": row.title,
        "status": row.status,
        "streak": row.streak,
        "wrong_count": row.wrong_count,
        "next_review": row.next_review.isoformat(),
        "note": row.note,
        "error_reason": row.error_reason,
    } for row in rows]


@router.post("/reviews/{item_id}/attempts", status_code=status.HTTP_201_CREATED)
def submit_review(item_id: int, payload: ReviewRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    item = db.scalar(select(ReviewItem).where(ReviewItem.id == item_id, ReviewItem.tenant_id == context.tenant_id))
    if item is None or item.status == "archived":
        raise HTTPException(status_code=404, detail="review item not found")
    previous_streak = item.streak
    if payload.result == "wrong":
        item.streak = 0
        item.wrong_count += 1
        item.status = "reviewing"
        item.next_review = date.today() + timedelta(days=1)
    elif payload.result == "postpone":
        item.next_review = date.today() + timedelta(days=1)
    elif payload.result == "mastered":
        item.status = "mastered"
        item.next_review = date.today() + timedelta(days=30)
    else:
        item.streak += 1
        intervals = (1, 3, 7, 14, 30)
        item.next_review = date.today() + timedelta(days=intervals[min(item.streak - 1, len(intervals) - 1)])
        item.status = "mastered" if item.streak >= 5 else "reviewing"
    attempt = ReviewAttempt(
        tenant_id=context.tenant_id,
        review_item_id=item.id,
        result=payload.result,
        previous_streak=previous_streak,
        next_review=item.next_review,
    )
    db.add(attempt)
    record_audit(db, context, "review.submit", "review_item", str(item.id), {"result": payload.result})
    db.commit()
    db.refresh(attempt)
    return {
        "id": attempt.id,
        "result": attempt.result,
        "next_review": item.next_review.isoformat(),
        "status": item.status,
        "streak": item.streak,
    }


@router.get("/reviews/{item_id}/attempts")
def list_review_attempts(item_id: int, context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    item_exists = db.scalar(
        select(ReviewItem.id).where(ReviewItem.id == item_id, ReviewItem.tenant_id == context.tenant_id)
    )
    if item_exists is None:
        raise HTTPException(status_code=404, detail="review item not found")
    rows = db.scalars(
        select(ReviewAttempt)
        .where(ReviewAttempt.review_item_id == item_id, ReviewAttempt.tenant_id == context.tenant_id)
        .order_by(ReviewAttempt.created_at.desc())
    ).all()
    return [{
        "id": row.id,
        "result": row.result,
        "previous_streak": row.previous_streak,
        "next_review": row.next_review.isoformat(),
        "created_at": row.created_at.isoformat(),
    } for row in rows]


@router.get("/study-sessions")
def list_study_sessions(
    context: CurrentContext, db: DbSession, course_id: int | None = None, limit: int = 100
) -> list[dict[str, object]]:
    bounded_limit = min(max(limit, 1), 500)
    statement = select(StudySession).where(StudySession.tenant_id == context.tenant_id)
    if course_id is not None:
        statement = statement.where(StudySession.course_id == course_id)
    rows = db.scalars(statement.order_by(StudySession.started_at.desc()).limit(bounded_limit)).all()
    return [{
        "id": row.id,
        "course_id": row.course_id,
        "task_id": row.task_id,
        "started_at": row.started_at.isoformat(),
        "ended_at": row.ended_at.isoformat() if row.ended_at else None,
        "duration_minutes": row.duration_minutes,
        "note": row.note,
    } for row in rows]


@router.post("/study-sessions", status_code=status.HTTP_201_CREATED)
def start_study_session(payload: StudySessionRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    if payload.course_id is not None and db.scalar(
        select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")
    if payload.task_id is not None:
        task = db.scalar(
            select(StudyTask).where(StudyTask.id == payload.task_id, StudyTask.tenant_id == context.tenant_id)
        )
        if task is None:
            raise HTTPException(status_code=404, detail="task not found")
        if payload.course_id is not None and task.course_id != payload.course_id:
            raise HTTPException(status_code=422, detail="task does not belong to the requested course")
        if payload.course_id is None:
            payload.course_id = task.course_id
    study_session = StudySession(
        tenant_id=context.tenant_id,
        course_id=payload.course_id,
        task_id=payload.task_id,
        note=payload.note.strip(),
    )
    db.add(study_session)
    db.flush()
    record_audit(db, context, "study_session.start", "study_session", str(study_session.id))
    db.commit()
    db.refresh(study_session)
    return {"id": study_session.id, "started_at": study_session.started_at.isoformat(), "tenant_id": context.tenant_id}


@router.post("/study-sessions/{session_id}/finish")
def finish_study_session(
    session_id: int, payload: StudySessionFinishRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    study_session = db.scalar(
        select(StudySession).where(StudySession.id == session_id, StudySession.tenant_id == context.tenant_id)
    )
    if study_session is None:
        raise HTTPException(status_code=404, detail="study session not found")
    if study_session.ended_at is not None:
        raise HTTPException(status_code=409, detail="study session is already finished")
    study_session.ended_at = datetime.now()
    study_session.duration_minutes = payload.duration_minutes
    if payload.note is not None:
        study_session.note = payload.note.strip()
    record_audit(db, context, "study_session.finish", "study_session", str(study_session.id), {"duration_minutes": payload.duration_minutes})
    db.commit()
    return {"id": study_session.id, "duration_minutes": study_session.duration_minutes, "ended_at": study_session.ended_at.isoformat()}


@router.get("/resources")
def list_resources(context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    rows = db.scalars(
        select(ResourceFile)
        .where(ResourceFile.tenant_id == context.tenant_id, ResourceFile.trashed.is_(False))
        .order_by(ResourceFile.id.desc())
    ).all()
    return [{"id": row.id, "name": row.name, "course_id": row.course_id, "size": row.size} for row in rows]


@router.post("/resources", status_code=status.HTTP_202_ACCEPTED)
def upload_resource(
    context: CurrentContext,
    db: DbSession,
    file: UploadFile = File(...),
    course_id: int | None = None,
) -> dict[str, object]:
    if course_id is not None and db.scalar(
        select(Course.id).where(Course.id == course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")
    filename = Path(file.filename or "upload").name
    if not filename or filename in {".", ".."}:
        raise HTTPException(status_code=422, detail="invalid filename")
    settings = get_server_settings()
    content = file.file.read(settings.upload_max_bytes + 1)
    if len(content) > settings.upload_max_bytes:
        raise HTTPException(status_code=413, detail="file exceeds upload limit")
    digest = hashlib.sha256(content).hexdigest()
    duplicate = db.scalar(
        select(ResourceFile.id).where(
            ResourceFile.tenant_id == context.tenant_id,
            ResourceFile.sha256 == digest,
            ResourceFile.trashed.is_(False),
        )
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="identical resource already exists")
    storage = S3ObjectStorage(settings)
    key = resource_key(tenant_id=context.tenant_id, resource_id=str(uuid4()), filename=filename)
    from io import BytesIO
    try:
        storage.put(key=key, stream=BytesIO(content), content_type=file.content_type or "application/octet-stream")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="object storage unavailable") from exc
    resource = ResourceFile(
        tenant_id=context.tenant_id,
        name=filename,
        original_name=filename,
        source_path="",
        relative_path=key,
        sha256=digest,
        size=len(content),
        course_id=course_id,
    )
    job = BackgroundJob(
        tenant_id=context.tenant_id,
        requested_by=context.user_id,
        job_type="index_resource",
        status="queued",
        payload="{}",
        detail="waiting for resource record",
    )
    db.add_all([resource, job])
    try:
        db.flush()
        job.payload = json.dumps({"resource_id": resource.id, "tenant_id": context.tenant_id}, ensure_ascii=False)
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(key=key)
        raise
    return {"resource_id": resource.id, "job_id": job.id, "status": job.status}


@router.post("/rag/jobs", status_code=status.HTTP_202_ACCEPTED)
def queue_rag_job(payload: RagRequest, context: CurrentContext, db: DbSession) -> dict[str, str]:
    """Queue boundary for the worker-backed RAG flow.

    The worker implementation will validate the same tenant scope before retrieval.
    Keeping this endpoint asynchronous prevents long LLM calls from consuming API workers.
    """
    if payload.course_id is not None and db.scalar(
        select(Course).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")
    import json
    job = BackgroundJob(
        tenant_id=context.tenant_id,
        requested_by=context.user_id,
        job_type="rag_question",
        status="queued",
        payload=json.dumps({"tenant_id": context.tenant_id, "question": payload.question, "course_id": payload.course_id}, ensure_ascii=False),
        detail="等待 worker 处理",
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return {"job_id": str(job.id), "status": job.status}


@router.post("/ai/question-generation/jobs", status_code=status.HTTP_202_ACCEPTED)
def queue_question_generation_job(payload: AiQuestionGenerationRequest, context: CurrentContext, db: DbSession) -> dict[str, str]:
    allowed_kinds = {"single_choice", "multiple_choice", "true_false", "short_answer"}
    if not set(payload.kinds) <= allowed_kinds:
        raise HTTPException(status_code=422, detail="unsupported question kind")
    course = db.scalar(select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id))
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    job = BackgroundJob(
        tenant_id=context.tenant_id,
        requested_by=context.user_id,
        job_type="generate_questions",
        status="queued",
        payload=json.dumps({"tenant_id": context.tenant_id, "course_id": payload.course_id, "request": payload.request, "count": payload.count, "difficulty": payload.difficulty, "kinds": payload.kinds}, ensure_ascii=False),
        detail="waiting for grounded AI question generation",
    )
    db.add(job)
    record_audit(db, context, "ai.question_generation.queue", "course", str(payload.course_id), {"count": payload.count})
    db.commit()
    return {"job_id": str(job.id), "status": job.status}


@router.post("/ai/jobs", status_code=status.HTTP_202_ACCEPTED)
def queue_ai_feature_job(payload: AiFeatureRequest, context: CurrentContext, db: DbSession) -> dict[str, str]:
    needs_course = {"knowledge_extraction", "research_curation"}
    needs_attempt = {"subjective_grading", "error_analysis"}
    if payload.feature in needs_course and payload.course_id is None:
        raise HTTPException(status_code=422, detail="course_id is required for this AI feature")
    if payload.feature in needs_attempt and payload.attempt_id is None:
        raise HTTPException(status_code=422, detail="attempt_id is required for this AI feature")
    if payload.feature == "learning_plan" and payload.goal_id is None:
        raise HTTPException(status_code=422, detail="goal_id is required for learning plan")
    if payload.course_id is not None and db.scalar(select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="course not found")
    data = payload.model_dump(mode="json")
    data.pop("feature")
    job = BackgroundJob(
        tenant_id=context.tenant_id,
        requested_by=context.user_id,
        job_type="ai_feature",
        status="queued",
        payload=json.dumps({"tenant_id": context.tenant_id, "feature": payload.feature, "data": data}, ensure_ascii=False),
        detail=f"waiting for AI feature: {payload.feature}",
    )
    db.add(job)
    record_audit(db, context, f"ai.{payload.feature}.queue", "ai_feature", payload.feature)
    db.commit()
    return {"job_id": str(job.id), "status": job.status}


@router.post("/agent/jobs", status_code=status.HTTP_202_ACCEPTED)
def queue_learning_agent_job(payload: AgentRequest, context: CurrentContext, db: DbSession) -> dict[str, str]:
    if payload.course_id is not None and db.scalar(select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="course not found")
    job = BackgroundJob(tenant_id=context.tenant_id, requested_by=context.user_id, job_type="learning_agent", status="queued", payload=json.dumps({"tenant_id": context.tenant_id, "data": payload.model_dump()}, ensure_ascii=False), detail="agent is analyzing your request")
    db.add(job)
    record_audit(db, context, "agent.run", "agent", "learning")
    db.commit()
    return {"job_id": str(job.id), "status": job.status}


@router.get("/agent/sessions")
def get_agent_sessions(context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    return list_sessions(db, context.tenant_id)


@router.get("/agent/tools")
def get_agent_tools(context: CurrentContext) -> list[dict[str, object]]:
    """Expose the same declared cloud tools to Web and desktop clients."""
    return tools_for_client("web")


@router.post("/agent/sessions", status_code=status.HTTP_201_CREATED)
def create_agent_session(payload: AgentSessionRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    from app.models import AgentSession
    item = AgentSession(tenant_id=context.tenant_id, title=payload.title.strip())
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "title": item.title, "updated_at": item.updated_at.isoformat()}


@router.get("/agent/sessions/{session_id}/messages")
def get_agent_messages(session_id: int, context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    try: return session_messages(db, context.tenant_id, session_id)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/agent/sessions/{session_id}/messages/stream")
def stream_agent_message(session_id: int, payload: AgentMessageRequest, context: CurrentContext, db: DbSession):
    if payload.course_id is not None and db.scalar(select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try: session_messages(db, context.tenant_id, session_id)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(
        stream_agent_reply(session_factory=session_factory(get_server_settings()), tenant_id=context.tenant_id, user_id=context.user_id, session_id=session_id, message=payload.message.strip(), course_id=payload.course_id),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/jobs/{job_id}")
def get_job(job_id: int, context: CurrentContext, db: DbSession) -> dict[str, object]:
    job = db.scalar(select(BackgroundJob).where(BackgroundJob.id == job_id, BackgroundJob.tenant_id == context.tenant_id))
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    result: dict[str, object] = {}
    if job.status == "completed" and job.detail:
        try:
            decoded = json.loads(job.detail)
            if isinstance(decoded, dict):
                result = decoded
        except json.JSONDecodeError:
            pass
    return {
        "id": job.id,
        "type": job.job_type,
        "status": job.status,
        "progress": job.progress,
        "detail": job.detail if not result else "",
        "error": job.error,
        "result": result,
    }


@router.get("/ai-runs/{run_id}")
def get_ai_run(run_id: int, context: CurrentContext, db: DbSession) -> dict[str, object]:
    run = db.scalar(select(AIRun).where(AIRun.id == run_id, AIRun.tenant_id == context.tenant_id))
    if run is None:
        raise HTTPException(status_code=404, detail="AI run not found")
    try:
        output = json.loads(run.output_json or "{}")
    except json.JSONDecodeError:
        output = {}
    citations = db.scalars(
        select(AICitation)
        .where(AICitation.ai_run_id == run.id, AICitation.tenant_id == context.tenant_id)
        .order_by(AICitation.citation_number)
    ).all()
    return {
        "id": run.id,
        "feature": run.feature,
        "status": run.status,
        "model_name": run.model_name,
        "output": output,
        "citations": [{
            "number": citation.citation_number,
            "chunk_id": citation.chunk_id,
            "quote_text": citation.quote_text,
            "relevance_score": citation.relevance_score,
        } for citation in citations],
    }
