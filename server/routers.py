from __future__ import annotations
from uuid import uuid4
import hashlib
import json
import re
import tempfile
from collections import Counter
from io import BytesIO
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from app.models import (
    BackgroundJob,
    AgentHandoff,
    AgentMemory,
    AgentWorkflow,
    AICitation,
    AIRun,
    AuditEvent,
    Course,
    CourseNote,
    KnowledgePoint,
    KnowledgePointDraft,
    KnowledgePointDraftCitation,
    QuestionDraft,
    QuestionDraftCitation,
    LearningEvent,
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
    DocumentChunk,
    StudyGoal,
    StudySession,
    StudyTask,
    TaskAssignment,
    User,
)
from server.config import get_server_settings
from server.deps import CurrentContext, DbSession, require_org_admin
from datetime import date, datetime, timedelta
from server.security import create_access_token, create_refresh_token, hash_password, hash_refresh_token, verify_password
from server.storage import S3ObjectStorage, resource_key
from server.agent_stream import learning_snapshot, list_sessions, session_messages, stream_agent_reply
from server.agent_tools import WebAgentToolExecutor
from server.db import session_factory
from app.agent_runtime import search_capabilities, tools_for_client
from app.services.research_curation import ResearchCurationService
from app.services.meta_coding import MetaCodeProposal
from ai.gateways import create_chat_model
from ai.config import get_ai_settings
from server.web_coding import propose_web_code, run_web_code

router = APIRouter(prefix="/v1")

CHOICE_QUESTION_KINDS = {"single_choice", "multiple_choice", "true_false"}
SUPPORTED_QUESTION_KINDS = {
    "single_choice", "multiple_choice", "true_false", "fill_blank",
    "short_answer", "calculation", "essay", "reading",
}


def _ensure_web_coding_enabled() -> None:
    if not get_server_settings().web_coding_enabled:
        raise HTTPException(status_code=503, detail="Coding Agent is disabled in this deployment")


def _choice_token(value: str) -> str:
    normalized = " ".join(value.strip().casefold().split())
    if normalized in {"true", "t", "正确", "对", "是"}:
        return "true"
    if normalized in {"false", "f", "错误", "错", "否"}:
        return "false"
    match = re.match(r"^([a-z])(?:[.、):：\s]|$)", normalized)
    return match.group(1) if match else normalized


def _normalized_answer(value: str, kind: str) -> str | tuple[str, ...]:
    if kind == "multiple_choice":
        tokens = {_choice_token(part) for part in re.split(r"[,;|\n]+", value) if part.strip()}
        return tuple(sorted(tokens))
    if kind in CHOICE_QUESTION_KINDS:
        return _choice_token(value)
    return " ".join(value.strip().casefold().split())
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

class AgentResourceImportRequest(BaseModel):
    url: str = Field(min_length=12, max_length=2000)
    course_id: int = Field(gt=0)
    confirmed: bool = False

class WebCodingRunRequest(BaseModel):
    confirmed: bool = False
class CourseRequest(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=10000)
    subject: str = Field(default="其他", max_length=60)


class CourseNoteRequest(BaseModel):
    title: str = Field(default="学习笔记", min_length=1, max_length=160)
    content: str = Field(default="", max_length=50000)


class CourseNoteUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    content: str | None = Field(default=None, max_length=50000)


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
    knowledge_point_id: int | None = Field(default=None, gt=0)


class TaskBulkDeleteRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=500)


class TaskUpdateRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    planned_date: date | None = None
    duration_minutes: int | None = Field(default=None, ge=1, le=1440)
    scheduled_time: str | None = Field(default=None, max_length=5)
    priority: str | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=10000)


class TaskActionRequest(BaseModel):
    action: str = Field(pattern="^(start|complete|postpone|skip)$")


class QuestionRequest(BaseModel):
    prompt: str = Field(min_length=1, max_length=20000)
    answer: str = Field(min_length=1, max_length=20000)
    kind: str = Field(default="single_choice", max_length=20)
    explanation: str = Field(default="", max_length=20000)
    options: str = Field(default="", max_length=20000)
    tags: str = Field(default="", max_length=300)
    difficulty: int = Field(default=3, ge=1, le=5)
    course_id: int | None = None
    knowledge_point_id: int | None = Field(default=None, gt=0)


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


class KnowledgeDraftReviewRequest(BaseModel):
    action: str = Field(pattern="^(accept|reject)$")
    review_note: str = Field(default="", max_length=10000)


class QuestionDraftReviewRequest(BaseModel):
    action: str = Field(pattern="^(accept|reject)$")
    review_note: str = Field(default="", max_length=10000)


class PracticeStartRequest(BaseModel):
    question_ids: list[int] = Field(min_length=1, max_length=100)
    course_id: int | None = None


class PracticeRecommendationRequest(BaseModel):
    course_id: int | None = None
    limit: int = Field(default=10, ge=1, le=30)


class PracticeAttemptRequest(BaseModel):
    response: str = Field(default="", max_length=20000)
    elapsed_seconds: int = Field(default=0, ge=0, le=86400)


class ReviewRequest(BaseModel):
    result: str = Field(pattern="^(correct|wrong|mastered|postpone)$")


class VocabularyRequest(BaseModel):
    word: str = Field(min_length=1, max_length=180)
    meaning: str = Field(min_length=1, max_length=2000)
    example: str = Field(default="", max_length=4000)
    course_id: int | None = None


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
    knowledge_point_id: int | None = Field(default=None, gt=0)
    request: str = Field(min_length=1, max_length=4000)
    count: int = Field(default=5, ge=1, le=20)
    difficulty: int = Field(default=3, ge=1, le=5)
    kinds: list[str] = Field(default_factory=lambda: ["single_choice", "short_answer"], min_length=1, max_length=4)
    resource_ids: list[int] = Field(default_factory=list, max_length=20)


class AiFeatureRequest(BaseModel):
    feature: str = Field(pattern="^(knowledge_extraction|subjective_grading|error_analysis|learning_plan|learning_report|research_curation|agent_chat)$")
    course_id: int | None = None
    resource_ids: list[int] = Field(default_factory=list, max_length=20)
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
    event_type: str | None = Field(default=None, max_length=80)
    event_payload: dict[str, object] | None = None


def _course_title_from_request(request: str) -> str:
    """Derive a stable learning subject, never a scheduling instruction, as a course title."""
    import re

    text = re.sub(r"\s+", " ", request).strip()
    explicit = re.search(r"[《\"]([^》\"]{2,80})[》\"]", text)
    if explicit:
        return explicit.group(1).strip()

    if re.search(r"(?:\bcet[- ]?6\b|大学英语六级|英语\s*6\s*级|英语六级)", text, re.IGNORECASE):
        focus = "听力与阅读" if "听力" in text and "阅读" in text else "备考"
        return f"大学英语六级：{focus}"

    topic = re.search(r"围绕\s*([^，。；;：:]{2,60}?)(?:安排|制定|生成|学习|练习|复习|，|。|；|;|$)", text)
    if topic:
        value = topic.group(1).strip(" ：:，,。")
        if value:
            prefix = "高等数学" if any(word in value for word in ("极限", "导数", "积分", "函数", "矩阵")) else "专题学习"
            return f"{prefix}：{value}"[:80]

    subject = re.sub(r"^(请|帮我|给我|立即|现在)?(生成|制定|创建|安排|开始)", "", text)
    subject = re.sub(r"(?:未来|接下来)?\s*\d+\s*天.*$", "", subject)
    subject = re.sub(r"(学习计划|练习题|题目|任务).*$", "", subject).strip(" ：:，,。")
    return subject[:80] or "AI 学习课程"


class LearningLaunchRequest(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    request: str = Field(min_length=1, max_length=4000)
    course_id: int | None = None
    target_date: date | None = None
    weekly_minutes: int = Field(default=420, ge=1, le=10080)
    question_count: int = Field(default=5, ge=1, le=20)
    vocabulary_count: int = Field(default=10, ge=1, le=30)


class DiagnosticLaunchRequest(BaseModel):
    request: str = Field(min_length=1, max_length=4000)
    course_id: int | None = Field(default=None, gt=0)
    count: int = Field(default=20, ge=1, le=30)


class AgentMemoryRequest(BaseModel):
    scope: str = Field(pattern="^(course|long_term)$")
    category: str = Field(pattern="^(goal|plan_preference|weak_point|learning_pace)$")
    content: dict[str, object]
    course_id: int | None = None
    confirmed: bool = False


class AgentToolRequest(BaseModel):
    tool_name: str = Field(min_length=1, max_length=120)
    arguments: dict[str, object] = Field(default_factory=dict)
    confirmed: bool = False


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


def record_learning_event(
    db: DbSession,
    context: CurrentContext,
    event_type: str,
    *,
    course_id: int | None = None,
    task_id: int | None = None,
    question_id: int | None = None,
    knowledge_point_id: int | None = None,
    payload: dict[str, object] | None = None,
) -> None:
    db.add(LearningEvent(
        tenant_id=context.tenant_id,
        user_id=context.user_id,
        event_type=event_type,
        course_id=course_id,
        task_id=task_id,
        question_id=question_id,
        knowledge_point_id=knowledge_point_id,
        payload_json=json.dumps(payload or {}, ensure_ascii=False),
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
    organization = db.get(Organization, context.tenant_id)
    return {"id": user.id, "email": user.email, "tenant_id": context.tenant_id, "display_name": user.display_name,
            "role": context.role, "organization_name": organization.name if organization else "Learning Space"}


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


@router.get("/today")
def today_learning_center(context: CurrentContext, db: DbSession) -> dict[str, object]:
    """Return the real, cross-module data used by the daily learning center."""
    today = date.today()
    tasks = db.scalars(select(StudyTask).where(
        StudyTask.tenant_id == context.tenant_id,
        StudyTask.planned_date == today,
    ).order_by(StudyTask.completed, StudyTask.priority, StudyTask.id)).all()
    due_reviews = db.scalars(select(ReviewItem).where(
        ReviewItem.tenant_id == context.tenant_id,
        ReviewItem.status.not_in(("archived", "mastered")),
        ReviewItem.next_review <= today,
    ).order_by(ReviewItem.next_review, ReviewItem.id).limit(50)).all()
    weak_points = db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.tenant_id == context.tenant_id,
        KnowledgePoint.mastery < 70,
    ).order_by(KnowledgePoint.mastery, KnowledgePoint.importance.desc(), KnowledgePoint.id).limit(8)).all()
    start_at = datetime.combine(today - timedelta(days=1), datetime.min.time())
    end_at = datetime.combine(today, datetime.min.time())
    yesterday = db.scalars(select(PracticeSession).where(
        PracticeSession.tenant_id == context.tenant_id,
        PracticeSession.started_at >= start_at,
        PracticeSession.started_at < end_at,
        PracticeSession.status == "completed",
    )).all()
    recent_reviews = db.scalars(select(ReviewItem).where(
        ReviewItem.tenant_id == context.tenant_id,
        ReviewItem.status != "archived",
    ).order_by(ReviewItem.created_at.desc(), ReviewItem.id.desc()).limit(30)).all()
    error_counts = Counter(
        item.error_reason.strip() for item in recent_reviews if item.error_reason and item.error_reason.strip()
    )
    focus_areas = [name for name, _count in error_counts.most_common(3)]
    yesterday_total = sum(item.total for item in yesterday)
    yesterday_correct = sum(item.correct for item in yesterday)
    planned_minutes = sum(item.duration_minutes for item in tasks)
    completed_minutes = sum(item.duration_minutes for item in tasks if item.completed)
    accuracy = round(yesterday_correct * 100 / yesterday_total, 1) if yesterday_total else None
    task_context = _task_context(db, context, tasks)
    recommended_minutes = max(10, min(45, len(due_reviews) * 5 + len(weak_points[:3]) * 5))
    if accuracy is not None:
        insight_parts = [f"昨天完成 {yesterday_total} 道题，正确率 {accuracy}%"]
        if weak_points:
            insight_parts.append(f"今天优先复习 {weak_points[0].name}")
        if focus_areas:
            insight_parts.append(f"近期常见错误：{'、'.join(focus_areas)}")
        insight = "。".join(insight_parts) + f"。建议先安排约 {recommended_minutes} 分钟。"
    elif weak_points:
        insight = f"当前掌握度最低的是 {weak_points[0].name}，建议先安排约 {recommended_minutes} 分钟专项练习。"
    elif due_reviews:
        insight = f"今天有 {len(due_reviews)} 项复习到期，建议先完成约 {recommended_minutes} 分钟复习。"
    else:
        insight = "完成一次练习后，系统会根据真实答题结果生成今日建议。"
    return {
        "date": today.isoformat(),
        "summary": {"planned_minutes": planned_minutes, "completed_minutes": completed_minutes,
                     "completion_rate": round(completed_minutes * 100 / planned_minutes, 1) if planned_minutes else 0.0},
        "tasks": [_serialize_task(item, task_context) for item in tasks],
        "reviews": {"due": len(due_reviews), "items": [{"id": item.id, "title": item.title,
                   "question_id": item.question_id, "wrong_count": item.wrong_count,
                   "next_review": item.next_review.isoformat()} for item in due_reviews]},
        "weak_points": [{"id": item.id, "course_id": item.course_id, "name": item.name,
                         "mastery": item.mastery, "importance": item.importance} for item in weak_points],
        "insight": {"text": insight, "yesterday_accuracy": accuracy,
                    "focus_areas": focus_areas, "recommended_minutes": recommended_minutes},
        "reminders": _build_reminders(context, db),
    }


def _build_reminders(context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    """Build actionable reminders from current records; never fabricate notifications."""
    today = date.today()
    reminders: list[dict[str, object]] = []
    tasks = db.scalars(select(StudyTask).where(
        StudyTask.tenant_id == context.tenant_id,
        StudyTask.completed.is_(False),
        StudyTask.planned_date <= today,
    ).order_by(StudyTask.planned_date, StudyTask.id).limit(50)).all()
    for task in tasks:
        if task.scheduled_time and task.planned_date == today:
            reminders.append({"id": f"task-fixed-{task.id}", "type": "fixed", "title": task.title,
                              "message": f"{task.title} · {task.duration_minutes} min",
                              "course_id": task.course_id, "task_id": task.id,
                              "due_at": f"{task.planned_date.isoformat()}T{task.scheduled_time}"})
        if task.source == "ai" and task.planned_date == today:
            reminders.append({"id": f"task-plan-{task.id}", "type": "learning_plan", "title": task.title,
                              "message": "学习计划中的任务仍未完成", "course_id": task.course_id, "task_id": task.id,
                              "due_at": task.planned_date.isoformat()})
        if task.planned_date < today:
            reminders.append({"id": f"task-overdue-{task.id}", "type": "incomplete", "title": task.title,
                              "message": f"已逾期 { (today - task.planned_date).days } 天，建议延期或完成",
                              "course_id": task.course_id, "task_id": task.id,
                              "due_at": task.planned_date.isoformat()})
    reviews = db.scalars(select(ReviewItem).where(
        ReviewItem.tenant_id == context.tenant_id,
        ReviewItem.status.not_in(("archived", "mastered")),
        ReviewItem.next_review <= today,
    ).order_by(ReviewItem.next_review, ReviewItem.id).limit(30)).all()
    if reviews:
        reminders.append({"id": "review-due", "type": "review", "title": "今日待复习",
                          "message": f"有 {len(reviews)} 个复习项目进入周期", "review_count": len(reviews),
                          "due_at": today.isoformat()})
    goals = db.scalars(select(StudyGoal).where(
        StudyGoal.tenant_id == context.tenant_id,
        StudyGoal.target_date >= today,
        StudyGoal.target_date <= today + timedelta(days=7),
        StudyGoal.status.not_in(("completed", "archived")),
    ).order_by(StudyGoal.target_date, StudyGoal.id).limit(20)).all()
    for goal in goals:
        reminders.append({"id": f"goal-deadline-{goal.id}", "type": "deadline", "title": goal.title,
                          "message": f"目标截止日期：{goal.target_date.isoformat()}", "goal_id": goal.id,
                          "course_id": goal.course_id, "due_at": goal.target_date.isoformat()})
    return reminders[:100]


@router.get("/reminders")
def list_reminders(context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    return _build_reminders(context, db)


@router.get("/analytics")
def learning_analytics(
    context: CurrentContext,
    db: DbSession,
    days: int | str = 7,
    course_id: int | None = None,
) -> dict[str, object]:
    """Return explainable learning trends for 7 days, 30 days, or all time."""
    all_time = str(days).lower() in {"all", "0"}
    if not all_time:
        try:
            days = int(days)
        except (TypeError, ValueError) as exc:
            raise HTTPException(status_code=422, detail="days must be 7, 30, or all") from exc
        if days not in {7, 30}:
            raise HTTPException(status_code=422, detail="days must be 7, 30, or all")
    end_date = date.today()
    if all_time:
        earliest = []
        earliest_study = db.scalar(select(func.min(StudySession.started_at)).where(StudySession.tenant_id == context.tenant_id))
        earliest_task = db.scalar(select(func.min(StudyTask.planned_date)).where(StudyTask.tenant_id == context.tenant_id))
        earliest_attempt = db.scalar(select(func.min(QuestionAttempt.attempted_at)).where(QuestionAttempt.tenant_id == context.tenant_id))
        for value in (earliest_study, earliest_task, earliest_attempt):
            if value is not None:
                earliest.append(value.date() if isinstance(value, datetime) else value)
        start_date = min(earliest) if earliest else end_date
    else:
        start_date = end_date - timedelta(days=int(days) - 1)
    if course_id is not None and db.scalar(select(Course.id).where(
        Course.id == course_id, Course.tenant_id == context.tenant_id
    )) is None:
        raise HTTPException(status_code=404, detail="course not found")
    begin = datetime.combine(start_date, datetime.min.time())
    finish = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    study_statement = select(StudySession).where(
        StudySession.tenant_id == context.tenant_id,
        StudySession.started_at >= begin,
        StudySession.started_at < finish,
    )
    task_statement = select(StudyTask).where(
        StudyTask.tenant_id == context.tenant_id,
        StudyTask.planned_date >= start_date,
        StudyTask.planned_date <= end_date,
    )
    attempt_statement = select(QuestionAttempt).where(
        QuestionAttempt.tenant_id == context.tenant_id,
        QuestionAttempt.attempted_at >= begin,
        QuestionAttempt.attempted_at < finish,
    )
    if course_id is not None:
        study_statement = study_statement.where(StudySession.course_id == course_id)
        task_statement = task_statement.where(StudyTask.course_id == course_id)
        attempt_statement = attempt_statement.join(Question, Question.id == QuestionAttempt.question_id).where(Question.course_id == course_id)
    studies = db.scalars(study_statement).all()
    tasks = db.scalars(task_statement).all()
    attempts = [item for item in db.scalars(attempt_statement).all() if item.correct is not None]
    reviews = db.scalars(select(ReviewItem).where(
        ReviewItem.tenant_id == context.tenant_id,
        ReviewItem.status != "archived",
    )).all()
    if course_id is not None:
        reviews = [item for item in reviews if item.question_id and db.scalar(
            select(Question.course_id).where(Question.id == item.question_id)
        ) == course_id]
    daily = {} if all_time else {start_date + timedelta(days=index): {"minutes": 0, "questions": 0, "correct": 0}
                                  for index in range(int(days))}
    for item in studies:
        daily.setdefault(item.started_at.date(), {"minutes": 0, "questions": 0, "correct": 0})
        daily[item.started_at.date()]["minutes"] += item.duration_minutes
    for item in attempts:
        daily.setdefault(item.attempted_at.date(), {"minutes": 0, "questions": 0, "correct": 0})
        daily[item.attempted_at.date()]["questions"] += 1
        daily[item.attempted_at.date()]["correct"] += int(item.correct is True)
    error_types: dict[str, int] = {}
    for item in reviews:
        if item.next_review <= end_date and item.status != "mastered":
            error_types[item.error_reason or "unknown"] = error_types.get(item.error_reason or "unknown", 0) + item.wrong_count
    weak = db.scalars(select(KnowledgePoint).where(
        KnowledgePoint.tenant_id == context.tenant_id,
        KnowledgePoint.mastery < 70,
        *( [KnowledgePoint.course_id == course_id] if course_id is not None else [] ),
    ).order_by(KnowledgePoint.mastery, KnowledgePoint.id).limit(10)).all()
    total = len(attempts)
    correct = sum(item.correct is True for item in attempts)
    return {
        "range": {"start": start_date.isoformat(), "end": end_date.isoformat(), "days": "all" if all_time else days},
        "summary": {"study_minutes": sum(item.duration_minutes for item in studies),
                    "tasks_total": len(tasks), "tasks_completed": sum(item.completed for item in tasks),
                    "questions": total, "accuracy": round(correct * 100 / total, 1) if total else 0.0,
                    "due_reviews": sum(1 for item in reviews if item.next_review <= end_date and item.status != "mastered")},
        "daily": [{"date": day.isoformat(), "minutes": values["minutes"], "questions": values["questions"],
                   "accuracy": round(values["correct"] * 100 / values["questions"], 1) if values["questions"] else 0.0}
                  for day, values in sorted(daily.items())],
        "error_types": [{"type": name, "count": count} for name, count in sorted(error_types.items(), key=lambda item: -item[1])],
        "weak_points": [{"id": item.id, "name": item.name, "mastery": item.mastery,
                         "practice_count": item.practice_count, "confidence": item.confidence} for item in weak],
    }


@router.get("/weekly-report")
def weekly_learning_report(
    context: CurrentContext,
    db: DbSession,
    start_date: date | None = None,
    end_date: date | None = None,
    course_id: int | None = None,
) -> dict[str, object]:
    """Return a deterministic, tenant-scoped weekly report from real records.

    The AI report job can add narrative later, but this endpoint is the
    authoritative numeric snapshot used by the product UI and exports.
    """
    report_end = end_date or date.today()
    report_start = start_date or (report_end - timedelta(days=6))
    if report_end < report_start:
        raise HTTPException(status_code=422, detail="end_date must not be earlier than start_date")
    if (report_end - report_start).days > 30:
        raise HTTPException(status_code=422, detail="weekly report range cannot exceed 31 days")
    if course_id is not None and db.scalar(select(Course.id).where(
        Course.id == course_id, Course.tenant_id == context.tenant_id
    )) is None:
        raise HTTPException(status_code=404, detail="course not found")

    begin = datetime.combine(report_start, datetime.min.time())
    finish = datetime.combine(report_end + timedelta(days=1), datetime.min.time())
    tasks_statement = select(StudyTask).where(
        StudyTask.tenant_id == context.tenant_id,
        StudyTask.planned_date >= report_start,
        StudyTask.planned_date <= report_end,
    )
    studies_statement = select(StudySession).where(
        StudySession.tenant_id == context.tenant_id,
        StudySession.started_at >= begin,
        StudySession.started_at < finish,
    )
    practices_statement = select(PracticeSession).where(
        PracticeSession.tenant_id == context.tenant_id,
        PracticeSession.started_at >= begin,
        PracticeSession.started_at < finish,
        PracticeSession.status == "completed",
    )
    review_attempts_statement = select(ReviewAttempt).where(
        ReviewAttempt.tenant_id == context.tenant_id,
        ReviewAttempt.created_at >= begin,
        ReviewAttempt.created_at < finish,
    )
    if course_id is not None:
        tasks_statement = tasks_statement.where(StudyTask.course_id == course_id)
        studies_statement = studies_statement.where(StudySession.course_id == course_id)
        practices_statement = practices_statement.where(PracticeSession.course_id == course_id)
        review_attempts_statement = review_attempts_statement.join(
            ReviewItem, ReviewItem.id == ReviewAttempt.review_item_id
        ).join(Question, Question.id == ReviewItem.question_id, isouter=True).where(
            Question.course_id == course_id
        )
    tasks = db.scalars(tasks_statement).all()
    studies = db.scalars(studies_statement).all()
    practices = db.scalars(practices_statement).all()
    review_attempts = db.scalars(review_attempts_statement).all()
    question_total = sum(item.total for item in practices)
    question_correct = sum(item.correct for item in practices)
    task_total = len(tasks)
    task_completed = sum(1 for item in tasks if item.completed)
    weak_statement = select(KnowledgePoint).where(
        KnowledgePoint.tenant_id == context.tenant_id,
        KnowledgePoint.mastery < 70,
    )
    if course_id is not None:
        weak_statement = weak_statement.where(KnowledgePoint.course_id == course_id)
    weak_statement = weak_statement.order_by(
        KnowledgePoint.mastery, KnowledgePoint.importance.desc(), KnowledgePoint.id
    ).limit(8)
    weak_points = db.scalars(weak_statement).all()
    wrong_reviews = sum(1 for item in review_attempts if item.result == "wrong")
    correct_reviews = sum(1 for item in review_attempts if item.result in {"correct", "mastered"})

    daily: dict[date, dict[str, int]] = {
        report_start + timedelta(days=offset): {"minutes": 0, "tasks_completed": 0, "questions": 0}
        for offset in range((report_end - report_start).days + 1)
    }
    for item in studies:
        daily.setdefault(item.started_at.date(), {"minutes": 0, "tasks_completed": 0, "questions": 0})["minutes"] += max(0, item.duration_minutes)
    for item in tasks:
        if item.completed:
            daily[item.planned_date]["tasks_completed"] += 1
    for item in practices:
        daily.setdefault(item.started_at.date(), {"minutes": 0, "tasks_completed": 0, "questions": 0})["questions"] += item.total

    accuracy = round(question_correct * 100 / question_total, 1) if question_total else 0.0
    completion_rate = round(task_completed * 100 / task_total, 1) if task_total else 0.0
    recommendations: list[str] = []
    if weak_points:
        recommendations.append(f"优先练习 {weak_points[0].name}，当前掌握度 {weak_points[0].mastery}%。")
    if question_total and accuracy < 70:
        recommendations.append("最近正确率低于 70%，先安排基础题和错题复习，再逐步提高难度。")
    if task_total and completion_rate < 70:
        recommendations.append("本周计划完成率偏低，建议把下周任务拆成更短的学习单元。")
    if not recommendations:
        recommendations.append("数据还不足以提出个性化调整，完成一次练习或学习任务后再生成报告。")
    return {
        "range": {"start": report_start.isoformat(), "end": report_end.isoformat()},
        "course_id": course_id,
        "has_data": bool(tasks or studies or practices or review_attempts or weak_points),
        "summary": {
            "study_minutes": sum(max(0, item.duration_minutes) for item in studies),
            "tasks_total": task_total,
            "tasks_completed": task_completed,
            "task_completion_rate": completion_rate,
            "questions": question_total,
            "correct": question_correct,
            "accuracy": accuracy,
            "reviews_total": len(review_attempts),
            "reviews_correct": correct_reviews,
            "reviews_wrong": wrong_reviews,
        },
        "weak_points": [{"id": item.id, "name": item.name, "mastery": item.mastery,
                         "practice_count": item.practice_count, "wrong_count": item.wrong_count} for item in weak_points],
        "recommendations": recommendations,
        "daily": [{"date": day.isoformat(), **values} for day, values in sorted(daily.items())],
    }


@router.get("/courses/{course_id}/workspace")
def course_workspace(course_id: int, context: CurrentContext, db: DbSession) -> dict[str, object]:
    course = db.scalar(select(Course).where(Course.id == course_id, Course.tenant_id == context.tenant_id))
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    goals = db.scalars(select(StudyGoal).where(StudyGoal.tenant_id == context.tenant_id,
                                                StudyGoal.course_id == course_id).order_by(StudyGoal.target_date)).all()
    points = db.scalars(select(KnowledgePoint).where(KnowledgePoint.tenant_id == context.tenant_id,
                                                     KnowledgePoint.course_id == course_id).order_by(KnowledgePoint.mastery, KnowledgePoint.id)).all()
    tasks = db.scalars(select(StudyTask).where(StudyTask.tenant_id == context.tenant_id,
                                               StudyTask.course_id == course_id).order_by(StudyTask.planned_date.desc(), StudyTask.id.desc()).limit(10)).all()
    question_count = db.scalar(select(func.count()).select_from(Question).where(
        Question.tenant_id == context.tenant_id, Question.course_id == course_id, Question.archived.is_(False))) or 0
    resource_count = db.scalar(select(func.count()).select_from(ResourceFile).where(
        ResourceFile.tenant_id == context.tenant_id, ResourceFile.course_id == course_id, ResourceFile.trashed.is_(False))) or 0
    mistake_count = db.scalar(select(func.count()).select_from(ReviewItem).join(
        Question, Question.id == ReviewItem.question_id
    ).where(ReviewItem.tenant_id == context.tenant_id, ReviewItem.status != "archived",
            Question.tenant_id == context.tenant_id, Question.course_id == course_id)) or 0
    completed_practice = db.scalars(select(PracticeSession).where(
        PracticeSession.tenant_id == context.tenant_id, PracticeSession.course_id == course_id,
        PracticeSession.status == "completed"
    ).order_by(PracticeSession.finished_at.desc(), PracticeSession.id.desc()).limit(8)).all()
    task_context = _task_context(db, context, tasks)
    return {"course": {"id": course.id, "name": course.name, "subject": course.subject,
                        "description": course.description, "target_date": course.target_date.isoformat() if course.target_date else None,
                        "target_score": course.target_score, "progress": course.progress},
            "goals": [{"id": goal.id, "title": goal.title, "target_date": goal.target_date.isoformat(),
                       "progress": goal.progress, "status": goal.status} for goal in goals],
            "knowledge": [{"id": point.id, "name": point.name, "mastery": point.mastery,
                           "difficulty": point.difficulty, "importance": point.importance} for point in points],
            "recent_tasks": [_serialize_task(task, task_context) for task in tasks],
            "question_count": question_count,
            "resource_count": resource_count,
            "mistake_count": mistake_count,
            "practice": {"sessions": len(completed_practice), "questions": sum(item.total for item in completed_practice),
                          "correct": sum(item.correct for item in completed_practice),
                          "accuracy": round(sum(item.correct for item in completed_practice) * 100 / sum(item.total for item in completed_practice), 1)
                          if sum(item.total for item in completed_practice) else 0.0}}


def _task_context(db: DbSession, context: CurrentContext, tasks: list[StudyTask]) -> dict[str, dict[int, object]]:
    """Resolve display metadata without trusting cross-tenant foreign keys."""
    course_ids = {task.course_id for task in tasks if task.course_id is not None}
    point_ids = {task.knowledge_point_id for task in tasks if task.knowledge_point_id is not None}
    courses = db.scalars(select(Course).where(Course.tenant_id == context.tenant_id, Course.id.in_(course_ids))).all() if course_ids else []
    points = db.scalars(select(KnowledgePoint).where(KnowledgePoint.tenant_id == context.tenant_id, KnowledgePoint.id.in_(point_ids))).all() if point_ids else []
    return {"courses": {item.id: item for item in courses}, "points": {item.id: item for item in points}}


def _serialize_task(task: StudyTask, task_context: dict[str, dict[int, object]]) -> dict[str, object]:
    course = task_context["courses"].get(task.course_id)
    point = task_context["points"].get(task.knowledge_point_id)
    return {
        "id": task.id,
        "title": task.title,
        "course_id": task.course_id,
        "course_name": course.name if course else None,
        "knowledge_point_id": task.knowledge_point_id,
        "knowledge_point_name": point.name if point else None,
        "source": task.source,
        "note": task.note,
        "task_type": task.task_type,
        "status": task.status,
        "started_at": task.started_at.isoformat() if task.started_at else None,
        "planned_date": task.planned_date.isoformat(),
        "duration_minutes": task.duration_minutes,
        "scheduled_time": task.scheduled_time,
        "priority": task.priority,
        "completed": task.completed,
    }


def _task_assignments(db: DbSession, tenant_id: str, task_id: int) -> list[TaskAssignment]:
    return db.scalars(select(TaskAssignment).where(
        TaskAssignment.tenant_id == tenant_id, TaskAssignment.task_id == task_id,
    ).order_by(TaskAssignment.position, TaskAssignment.id)).all()


def _task_learning_payload(db: DbSession, context: CurrentContext, task: StudyTask) -> dict[str, object]:
    assignments = _task_assignments(db, context.tenant_id, task.id)
    point_ids = [item.knowledge_point_id for item in assignments if item.knowledge_point_id]
    question_ids = [item.question_id for item in assignments if item.question_id]
    review_ids = [item.review_item_id for item in assignments if item.review_item_id]
    points = db.scalars(select(KnowledgePoint).where(KnowledgePoint.tenant_id == context.tenant_id, KnowledgePoint.id.in_(point_ids))).all() if point_ids else []
    questions = db.scalars(select(Question).where(Question.tenant_id == context.tenant_id, Question.id.in_(question_ids), Question.archived.is_(False))).all() if question_ids else []
    reviews = db.scalars(select(ReviewItem).where(ReviewItem.tenant_id == context.tenant_id, ReviewItem.id.in_(review_ids))).all() if review_ids else []
    point_map, question_map, review_map = ({item.id: item for item in points}, {item.id: item for item in questions}, {item.id: item for item in reviews})
    return {
        "knowledge": [{"id": item.id, "name": item.name, "definition": item.definition, "formula": item.formula, "note": item.note, "mastery": item.mastery} for item in (point_map[point_id] for point_id in point_ids if point_id in point_map)],
        "questions": [{"id": item.id, "prompt": item.prompt, "kind": item.kind, "options": item.options, "explanation": item.explanation, "difficulty": item.difficulty} for item in (question_map[question_id] for question_id in question_ids if question_id in question_map)],
        "vocabulary": [{"id": item.id, "word": item.title, "meaning": item.note.split("\n", 1)[0], "example": item.note.split("\n", 1)[1] if "\n" in item.note else ""} for item in (review_map[review_id] for review_id in review_ids if review_id in review_map)],
        "requires_practice": bool(question_ids),
    }


@router.get("/mistakes")
def list_mistakes(context: CurrentContext, db: DbSession, course_id: int | None = None) -> list[dict[str, object]]:
    statement = select(ReviewItem, Question, KnowledgePoint).join(
        Question, Question.id == ReviewItem.question_id, isouter=True
    ).join(KnowledgePoint, KnowledgePoint.id == Question.knowledge_point_id, isouter=True).where(
        ReviewItem.tenant_id == context.tenant_id, ReviewItem.source != "vocabulary",
        ReviewItem.status != "archived",
    )
    if course_id is not None:
        statement = statement.where(Question.course_id == course_id)
    rows = db.execute(statement.order_by(ReviewItem.next_review, ReviewItem.id)).all()
    result = []
    for item, question, point in rows:
        latest_attempt = db.scalar(select(QuestionAttempt).where(
            QuestionAttempt.tenant_id == context.tenant_id,
            QuestionAttempt.question_id == item.question_id,
            QuestionAttempt.correct.is_(False),
        ).order_by(QuestionAttempt.attempted_at.desc(), QuestionAttempt.id.desc())) if item.question_id else None
        result.append({"id": item.id, "question_id": item.question_id, "title": item.title,
                       "user_answer": latest_attempt.response if latest_attempt else "",
                       "correct_answer": question.answer if question else "",
                       "error_type": item.error_reason or "unknown", "knowledge_point": point.name if point else None,
                       "wrong_count": item.wrong_count, "next_review": item.next_review.isoformat(),
                       "created_at": item.created_at.isoformat() if item.created_at else None,
                       "last_reviewed_at": item.last_reviewed_at.isoformat() if item.last_reviewed_at else None,
                       "note": item.note, "ai_analysis": item.ai_analysis,
                       "status": item.status})
    return result


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


def _serialize_course_note(note: CourseNote) -> dict[str, object]:
    return {
        "id": note.id,
        "course_id": note.course_id,
        "title": note.title,
        "content": note.content,
        "created_at": note.created_at.isoformat() if note.created_at else None,
        "updated_at": note.updated_at.isoformat() if note.updated_at else None,
    }


def _get_course_for_context(course_id: int, context: CurrentContext, db: DbSession) -> Course:
    course = db.scalar(select(Course).where(Course.id == course_id, Course.tenant_id == context.tenant_id))
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    return course


@router.get("/courses/{course_id}/notes")
def list_course_notes(course_id: int, context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    _get_course_for_context(course_id, context, db)
    notes = db.scalars(
        select(CourseNote).where(
            CourseNote.tenant_id == context.tenant_id,
            CourseNote.course_id == course_id,
        ).order_by(CourseNote.updated_at.desc(), CourseNote.id.desc())
    ).all()
    return [_serialize_course_note(note) for note in notes]


@router.post("/courses/{course_id}/notes", status_code=status.HTTP_201_CREATED)
def create_course_note(
    course_id: int, payload: CourseNoteRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    _get_course_for_context(course_id, context, db)
    note = CourseNote(
        tenant_id=context.tenant_id,
        course_id=course_id,
        title=payload.title.strip(),
        content=payload.content,
    )
    db.add(note)
    db.flush()
    record_audit(db, context, "course_note.create", "course_note", str(note.id), {"course_id": course_id})
    db.commit()
    db.refresh(note)
    return _serialize_course_note(note)


@router.patch("/course-notes/{note_id}")
def update_course_note(
    note_id: int, payload: CourseNoteUpdateRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    note = db.scalar(select(CourseNote).where(CourseNote.id == note_id, CourseNote.tenant_id == context.tenant_id))
    if note is None:
        raise HTTPException(status_code=404, detail="course note not found")
    if payload.title is not None:
        note.title = payload.title.strip()
    if payload.content is not None:
        note.content = payload.content
    record_audit(db, context, "course_note.update", "course_note", str(note.id), {"course_id": note.course_id})
    db.commit()
    db.refresh(note)
    return _serialize_course_note(note)


@router.delete("/course-notes/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_course_note(note_id: int, context: CurrentContext, db: DbSession) -> None:
    note = db.scalar(select(CourseNote).where(CourseNote.id == note_id, CourseNote.tenant_id == context.tenant_id))
    if note is None:
        raise HTTPException(status_code=404, detail="course note not found")
    record_audit(db, context, "course_note.delete", "course_note", str(note.id), {"course_id": note.course_id})
    db.delete(note)
    db.commit()


@router.get("/tasks")
def list_tasks(
    context: CurrentContext,
    db: DbSession,
    start: date | None = None,
    end: date | None = None,
    course_id: int | None = None,
) -> list[dict[str, object]]:
    statement = select(StudyTask).where(StudyTask.tenant_id == context.tenant_id)
    if start is not None:
        statement = statement.where(StudyTask.planned_date >= start)
    if end is not None:
        statement = statement.where(StudyTask.planned_date <= end)
    if course_id is not None:
        statement = statement.where(StudyTask.course_id == course_id)
    rows = db.scalars(statement.order_by(StudyTask.planned_date, StudyTask.id)).all()
    return [_serialize_task(row, _task_context(db, context, rows)) for row in rows]


@router.post("/tasks", status_code=status.HTTP_201_CREATED)
def create_task(payload: TaskRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    if payload.course_id is not None and db.scalar(
        select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")
    point = None
    if payload.knowledge_point_id is not None:
        point = db.scalar(select(KnowledgePoint).where(
            KnowledgePoint.id == payload.knowledge_point_id,
            KnowledgePoint.tenant_id == context.tenant_id,
        ))
        if point is None:
            raise HTTPException(status_code=404, detail="knowledge point not found")
        if payload.course_id is not None and point.course_id != payload.course_id:
            raise HTTPException(status_code=422, detail="knowledge point must belong to the selected course")
    course_id = payload.course_id or (point.course_id if point else None)
    task = StudyTask(
        tenant_id=context.tenant_id,
        title=payload.title.strip(),
        duration_minutes=payload.duration_minutes,
        planned_date=payload.planned_date or date.today(),
        priority=payload.priority,
        scheduled_time=payload.scheduled_time,
        note=payload.note,
        course_id=course_id,
        knowledge_point_id=payload.knowledge_point_id,
        status="planned",
    )
    db.add(task)
    db.flush()
    record_audit(db, context, "task.create", "study_task", str(task.id), {"title": task.title})
    db.commit()
    db.refresh(task)
    return {"id": task.id, "title": task.title, "tenant_id": context.tenant_id}


@router.delete("/tasks")
def delete_tasks_bulk(payload: TaskBulkDeleteRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    """Delete only the tasks explicitly selected in this workspace."""
    task_ids = list(dict.fromkeys(payload.task_ids))
    rows = db.scalars(select(StudyTask).where(
        StudyTask.id.in_(task_ids), StudyTask.tenant_id == context.tenant_id,
    )).all()
    for task in rows:
        db.delete(task)
    record_audit(db, context, "task.bulk_delete", "study_task", ",".join(str(task.id) for task in rows), {"requested_count": len(task_ids), "deleted_count": len(rows)})
    db.commit()
    return {"deleted_count": len(rows)}


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, payload: TaskUpdateRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    task = db.scalar(select(StudyTask).where(StudyTask.id == task_id, StudyTask.tenant_id == context.tenant_id))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    changes = payload.model_dump(exclude_unset=True)
    if "title" in changes:
        task.title = str(changes["title"]).strip()
    for field in ("planned_date", "duration_minutes", "scheduled_time", "priority", "note"):
        if field in changes:
            setattr(task, field, changes[field])
    record_audit(db, context, "task.update", "study_task", str(task.id), changes)
    db.commit()
    db.refresh(task)
    return {"id": task.id, "status": task.status, "planned_date": task.planned_date.isoformat(), "updated": list(changes)}


@router.post("/tasks/{task_id}/complete")
def complete_task(task_id: int, context: CurrentContext, db: DbSession) -> dict[str, object]:
    task = db.scalar(select(StudyTask).where(StudyTask.id == task_id, StudyTask.tenant_id == context.tenant_id))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    learning = _task_learning_payload(db, context, task)
    if learning["requires_practice"]:
        raise HTTPException(status_code=409, detail="complete the assigned questions from this task before marking it complete")
    if not task.completed:
        task.completed = True
        task.status = "completed"
        task.completed_at = datetime.now()
        record_audit(db, context, "task.complete", "study_task", str(task.id))
        record_learning_event(db, context, "task_completed", course_id=task.course_id, task_id=task.id,
                              payload={"duration_minutes": task.duration_minutes})
        db.commit()
    return {"id": task.id, "completed": task.completed}


@router.post("/tasks/{task_id}/action")
def act_on_task(task_id: int, payload: TaskActionRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    task = db.scalar(select(StudyTask).where(StudyTask.id == task_id, StudyTask.tenant_id == context.tenant_id))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    if payload.action == "start":
        if task.completed:
            raise HTTPException(status_code=422, detail="completed task cannot be started")
        task.status = "in_progress"
        task.started_at = task.started_at or datetime.now()
        event_type = "task_started"
    elif payload.action == "complete":
        if _task_learning_payload(db, context, task)["requires_practice"]:
            raise HTTPException(status_code=409, detail="complete the assigned questions from this task before marking it complete")
        task.completed = True
        task.status = "completed"
        task.completed_at = datetime.now()
        event_type = "task_completed"
    elif payload.action == "skip":
        task.completed = True
        task.status = "skipped"
        task.completed_at = datetime.now()
        event_type = "task_skipped"
    else:
        task.planned_date = max(task.planned_date, date.today()) + timedelta(days=1)
        task.completed = False
        task.status = "planned"
        event_type = "task_postponed"
    record_audit(db, context, f"task.{payload.action}", "study_task", str(task.id),
                 {"planned_date": task.planned_date.isoformat()})
    record_learning_event(db, context, event_type, course_id=task.course_id, task_id=task.id,
                          payload={"planned_date": task.planned_date.isoformat()})
    db.commit()
    return {"id": task.id, "action": payload.action, "planned_date": task.planned_date.isoformat(),
            "completed": task.completed, "status": task.status}


@router.get("/tasks/{task_id}/learning")
def get_task_learning(task_id: int, context: CurrentContext, db: DbSession) -> dict[str, object]:
    task = db.scalar(select(StudyTask).where(StudyTask.id == task_id, StudyTask.tenant_id == context.tenant_id))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    return {"task_id": task.id, **_task_learning_payload(db, context, task)}


@router.post("/tasks/{task_id}/practice", status_code=status.HTTP_201_CREATED)
def start_task_practice(task_id: int, context: CurrentContext, db: DbSession) -> dict[str, object]:
    task = db.scalar(select(StudyTask).where(StudyTask.id == task_id, StudyTask.tenant_id == context.tenant_id))
    if task is None:
        raise HTTPException(status_code=404, detail="task not found")
    question_ids = [item.question_id for item in _task_assignments(db, context.tenant_id, task.id) if item.question_id]
    if not question_ids:
        raise HTTPException(status_code=409, detail="this task has no assigned questions yet")
    running = db.scalar(select(PracticeSession).where(PracticeSession.tenant_id == context.tenant_id, PracticeSession.task_id == task.id, PracticeSession.status == "running"))
    if running is not None:
        return {"id": running.id, "task_id": task.id, "total": running.total, "status": running.status}
    task.status = "in_progress"; task.started_at = task.started_at or datetime.now()
    session = PracticeSession(tenant_id=context.tenant_id, course_id=task.course_id, task_id=task.id, total=len(question_ids))
    db.add(session); db.flush()
    db.add_all([PracticeSessionQuestion(tenant_id=context.tenant_id, session_id=session.id, question_id=question_id, position=position) for position, question_id in enumerate(question_ids, start=1)])
    record_learning_event(db, context, "task_practice_started", course_id=task.course_id, task_id=task.id, payload={"practice_session_id": session.id, "question_count": len(question_ids)})
    db.commit()
    return {"id": session.id, "task_id": task.id, "total": session.total, "status": session.status}


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
        "explanation": row.explanation,
        "options": row.options,
        "course_id": row.course_id,
        "knowledge_point_id": row.knowledge_point_id,
        "difficulty": row.difficulty,
        "tags": row.tags,
    } for row in rows]


@router.post("/practice/recommendations")
def recommend_practice(
    payload: PracticeRecommendationRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    """Select practice from mastery, due reviews, recent errors and difficulty."""
    if payload.course_id is not None and db.scalar(select(Course.id).where(
        Course.id == payload.course_id, Course.tenant_id == context.tenant_id
    )) is None:
        raise HTTPException(status_code=404, detail="course not found")
    point_statement = select(KnowledgePoint).where(KnowledgePoint.tenant_id == context.tenant_id)
    question_statement = select(Question).where(
        Question.tenant_id == context.tenant_id, Question.archived.is_(False)
    )
    if payload.course_id is not None:
        point_statement = point_statement.where(KnowledgePoint.course_id == payload.course_id)
        question_statement = question_statement.where(Question.course_id == payload.course_id)
    points = {point.id: point for point in db.scalars(point_statement).all()}
    questions = db.scalars(question_statement).all()
    due_items = db.scalars(select(ReviewItem).where(
        ReviewItem.tenant_id == context.tenant_id,
        ReviewItem.status.not_in(("archived", "mastered")),
        ReviewItem.next_review <= date.today(),
        ReviewItem.question_id.is_not(None),
    )).all()
    due_ids = {item.question_id for item in due_items}
    recent_wrong = db.scalars(select(QuestionAttempt).where(
        QuestionAttempt.tenant_id == context.tenant_id,
        QuestionAttempt.correct.is_(False),
        QuestionAttempt.attempted_at >= datetime.now() - timedelta(days=30),
    )).all()
    wrong_ids = {item.question_id for item in recent_wrong}
    ranked: list[tuple[float, Question, str]] = []
    for question in questions:
        point = points.get(question.knowledge_point_id)
        mastery = point.mastery if point else 50
        target_difficulty = 1 if mastery < 40 else (2 if mastery < 70 else 4)
        score = float((100 - mastery) * 2 + max(0, 5 - abs(question.difficulty - target_difficulty)) * 5)
        reasons: list[str] = []
        if question.id in due_ids:
            score += 1000
            reasons.append("到期复习")
        if question.id in wrong_ids:
            score += 300
            reasons.append("最近答错")
        if point and point.mastery < 70:
            reasons.append(f"薄弱知识点 {point.name}")
        if not reasons:
            reasons.append("匹配当前难度")
        ranked.append((score, question, "；".join(reasons)))
    ranked.sort(key=lambda item: (-item[0], item[1].id))
    selected = ranked[:payload.limit]
    return {
        "strategy": "due_review → recent_errors → weak_points → adaptive_difficulty",
        "items": [{
            "id": question.id,
            "prompt": question.prompt,
            "kind": question.kind,
            "course_id": question.course_id,
            "knowledge_point_id": question.knowledge_point_id,
            "difficulty": question.difficulty,
            "mastery": points[question.knowledge_point_id].mastery if question.knowledge_point_id in points else None,
            "reason": reason,
            "due": question.id in due_ids,
        } for _, question, reason in selected],
        "empty_reason": "暂无可推荐题目，请先创建题目或从课程资料生成题目。" if not selected else None,
    }


@router.post("/questions", status_code=status.HTTP_201_CREATED)
def create_question(payload: QuestionRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    if payload.kind not in SUPPORTED_QUESTION_KINDS:
        raise HTTPException(status_code=422, detail="unsupported question kind")
    if payload.course_id is not None and db.scalar(
        select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)
    ) is None:
        raise HTTPException(status_code=404, detail="course not found")
    if payload.knowledge_point_id is not None:
        point = db.scalar(
            select(KnowledgePoint).where(
                KnowledgePoint.id == payload.knowledge_point_id,
                KnowledgePoint.tenant_id == context.tenant_id,
            )
        )
        if point is None:
            raise HTTPException(status_code=404, detail="knowledge point not found")
        if payload.course_id is not None and point.course_id != payload.course_id:
            raise HTTPException(status_code=422, detail="knowledge point must belong to the requested course")
        if payload.course_id is None:
            payload.course_id = point.course_id
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
        knowledge_point_id=payload.knowledge_point_id,
    )
    db.add(question)
    db.flush()
    record_audit(db, context, "question.create", "question", str(question.id))
    db.commit()
    db.refresh(question)
    return {"id": question.id, "course_id": question.course_id,
            "knowledge_point_id": question.knowledge_point_id, "tenant_id": context.tenant_id}


@router.get("/goals")
def list_goals(context: CurrentContext, db: DbSession, course_id: int | None = None) -> list[dict[str, object]]:
    filters = [StudyGoal.tenant_id == context.tenant_id]
    if course_id is not None:
        filters.append(StudyGoal.course_id == course_id)
    rows = db.scalars(
        select(StudyGoal)
        .where(*filters)
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
    def json_values(value: str) -> list[object]:
        try:
            decoded = json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        return decoded if isinstance(decoded, list) else []

    return [{
        "id": row.id,
        "course_id": row.course_id,
        "name": row.name,
        "mastery": row.mastery,
        "category": row.category,
        "difficulty": row.difficulty,
        "importance": row.importance,
        "confidence": row.confidence,
        "practice_count": row.practice_count,
        "correct_count": row.correct_count,
        "wrong_count": row.wrong_count,
        "last_studied_at": row.last_studied_at.isoformat() if row.last_studied_at else None,
        "next_review_at": row.next_review_at.isoformat() if row.next_review_at else None,
        "definition": row.definition,
        "formula": row.formula,
        "note": row.note,
        "prerequisites": json_values(row.prerequisites_json),
        "related_points": json_values(row.related_points_json),
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


@router.get("/knowledge-drafts")
def list_knowledge_drafts(
    context: CurrentContext, db: DbSession, course_id: int | None = None, status_filter: str = "pending"
) -> list[dict[str, object]]:
    statement = select(KnowledgePointDraft).where(KnowledgePointDraft.tenant_id == context.tenant_id)
    if course_id is not None:
        if db.scalar(select(Course.id).where(Course.id == course_id, Course.tenant_id == context.tenant_id)) is None:
            raise HTTPException(status_code=404, detail="course not found")
        statement = statement.where(KnowledgePointDraft.course_id == course_id)
    if status_filter:
        if status_filter not in {"pending", "accepted", "rejected"}:
            raise HTTPException(status_code=422, detail="invalid draft status")
        statement = statement.where(KnowledgePointDraft.status == status_filter)
    drafts = db.scalars(statement.order_by(KnowledgePointDraft.id.desc()).limit(100)).all()
    draft_ids = [item.id for item in drafts]
    citations_by_draft: dict[int, list[dict[str, object]]] = {item.id: [] for item in drafts}
    if draft_ids:
        rows = db.execute(
            select(KnowledgePointDraftCitation, DocumentChunk, ResourceFile)
            .join(DocumentChunk, DocumentChunk.id == KnowledgePointDraftCitation.chunk_id)
            .join(ResourceFile, ResourceFile.id == DocumentChunk.resource_id, isouter=True)
            .where(KnowledgePointDraftCitation.draft_id.in_(draft_ids), DocumentChunk.tenant_id == context.tenant_id)
        ).all()
        for link, chunk, resource in rows:
            citations_by_draft[link.draft_id].append({
                "chunk_id": chunk.id,
                "source_name": resource.name if resource else "未知资料",
                "location_label": chunk.location_label,
                "quote_text": link.quote_text,
            })
    return [{
        "id": item.id,
        "ai_run_id": item.ai_run_id,
        "course_id": item.course_id,
        "name": item.name,
        "category": item.category,
        "definition": item.definition,
        "formula": item.formula,
        "difficulty": item.difficulty,
        "importance": item.importance,
        "confidence": item.confidence,
        "status": item.status,
        "review_note": item.review_note,
        "accepted_knowledge_point_id": item.accepted_knowledge_point_id,
        "citations": citations_by_draft[item.id],
    } for item in drafts]


@router.post("/knowledge-drafts/{draft_id}/review")
def review_knowledge_draft(
    draft_id: int, payload: KnowledgeDraftReviewRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    draft = db.scalar(select(KnowledgePointDraft).where(
        KnowledgePointDraft.id == draft_id, KnowledgePointDraft.tenant_id == context.tenant_id
    ))
    if draft is None:
        raise HTTPException(status_code=404, detail="knowledge draft not found")
    if draft.status != "pending":
        raise HTTPException(status_code=409, detail="knowledge draft has already been reviewed")
    draft.review_note = payload.review_note.strip()
    draft.reviewed_at = datetime.now()
    accepted_id: int | None = None
    if payload.action == "accept":
        point = db.scalar(select(KnowledgePoint).where(
            KnowledgePoint.tenant_id == context.tenant_id,
            KnowledgePoint.course_id == draft.course_id,
            KnowledgePoint.name == draft.name,
        ))
        if point is None:
            point = KnowledgePoint(
                tenant_id=context.tenant_id, course_id=draft.course_id, name=draft.name, source="ai"
            )
            db.add(point)
        point.category = draft.category
        point.definition = draft.definition
        point.formula = draft.formula
        point.prerequisites_json = draft.prerequisites_json
        point.related_points_json = draft.related_points_json
        point.common_mistakes_json = draft.common_mistakes_json
        point.difficulty = draft.difficulty
        point.importance = draft.importance
        point.confidence = draft.confidence
        point.note = payload.review_note.strip()
        point.source = "ai"
        db.flush()
        accepted_id = point.id
        draft.status = "accepted"
        draft.accepted_knowledge_point_id = accepted_id
        record_learning_event(db, context, "knowledge_extracted", course_id=draft.course_id,
                              knowledge_point_id=accepted_id, payload={"draft_id": draft.id})
    else:
        draft.status = "rejected"
    record_audit(db, context, f"knowledge_draft.{payload.action}", "knowledge_point_draft", str(draft.id),
                 {"knowledge_point_id": accepted_id})
    db.commit()
    return {"id": draft.id, "status": draft.status, "knowledge_point_id": accepted_id}


@router.get("/question-drafts")
def list_question_drafts(
    context: CurrentContext, db: DbSession, course_id: int | None = None, status_filter: str = "pending"
) -> list[dict[str, object]]:
    statement = select(QuestionDraft).where(QuestionDraft.tenant_id == context.tenant_id)
    if course_id is not None:
        if db.scalar(select(Course.id).where(Course.id == course_id, Course.tenant_id == context.tenant_id)) is None:
            raise HTTPException(status_code=404, detail="course not found")
        statement = statement.where(QuestionDraft.course_id == course_id)
    if status_filter:
        if status_filter not in {"pending", "accepted", "rejected"}:
            raise HTTPException(status_code=422, detail="invalid draft status")
        statement = statement.where(QuestionDraft.status == status_filter)
    drafts = db.scalars(statement.order_by(QuestionDraft.id.desc()).limit(100)).all()
    draft_ids = [item.id for item in drafts]
    citations_by_draft: dict[int, list[dict[str, object]]] = {item.id: [] for item in drafts}
    if draft_ids:
        rows = db.execute(
            select(QuestionDraftCitation, DocumentChunk, ResourceFile)
            .join(DocumentChunk, DocumentChunk.id == QuestionDraftCitation.chunk_id)
            .join(ResourceFile, ResourceFile.id == DocumentChunk.resource_id, isouter=True)
            .where(QuestionDraftCitation.question_draft_id.in_(draft_ids), DocumentChunk.tenant_id == context.tenant_id)
        ).all()
        for link, chunk, resource in rows:
            citations_by_draft[link.question_draft_id].append({
                "chunk_id": chunk.id,
                "citation_number": link.citation_number,
                "source_name": resource.name if resource else "未知资料",
                "location_label": chunk.location_label,
                "quote_text": link.quote_text,
            })
    def decoded(value: str, fallback: object) -> object:
        try:
            result = json.loads(value or "")
            return result
        except (TypeError, json.JSONDecodeError):
            return fallback
    return [{
        "id": item.id, "ai_run_id": item.ai_run_id, "course_id": item.course_id,
        "knowledge_point_id": item.knowledge_point_id, "kind": item.kind,
        "prompt": item.prompt, "answer": item.answer, "explanation": item.explanation,
        "options": decoded(item.options_json, []), "tags": decoded(item.tags_json, []),
        "difficulty": item.difficulty, "status": item.status, "review_note": item.review_note,
        "accepted_question_id": item.accepted_question_id,
        "citations": citations_by_draft[item.id],
    } for item in drafts]


@router.post("/question-drafts/{draft_id}/review")
def review_question_draft(
    draft_id: int, payload: QuestionDraftReviewRequest, context: CurrentContext, db: DbSession
) -> dict[str, object]:
    draft = db.scalar(select(QuestionDraft).where(
        QuestionDraft.id == draft_id, QuestionDraft.tenant_id == context.tenant_id
    ))
    if draft is None:
        raise HTTPException(status_code=404, detail="question draft not found")
    if draft.status != "pending":
        raise HTTPException(status_code=409, detail="question draft has already been reviewed")
    draft.review_note = payload.review_note.strip()
    draft.reviewed_at = datetime.now()
    question_id: int | None = None
    if payload.action == "accept":
        try:
            options = json.loads(draft.options_json or "[]")
            tags = json.loads(draft.tags_json or "[]")
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=422, detail="question draft has invalid structured fields") from exc
        if not isinstance(options, list) or not isinstance(tags, list):
            raise HTTPException(status_code=422, detail="question draft has invalid structured fields")
        question = Question(
            tenant_id=context.tenant_id, course_id=draft.course_id,
            knowledge_point_id=draft.knowledge_point_id, kind=draft.kind,
            prompt=draft.prompt, answer=draft.answer, explanation=draft.explanation,
            options="\n".join(str(value) for value in options),
            tags=", ".join(str(value) for value in tags), difficulty=draft.difficulty, source="ai",
        )
        db.add(question)
        db.flush()
        question_id = question.id
        draft.accepted_question_id = question_id
        draft.status = "accepted"
        record_learning_event(db, context, "question_draft_accepted", course_id=draft.course_id,
                              question_id=question_id, payload={"draft_id": draft.id})
    else:
        draft.status = "rejected"
    record_audit(db, context, f"question_draft.{payload.action}", "question_draft", str(draft.id),
                 {"question_id": question_id})
    db.commit()
    return {"id": draft.id, "status": draft.status, "question_id": question_id}


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
    correct = _normalized_answer(payload.response, question.kind) == _normalized_answer(question.answer, question.kind)
    error_type = "" if correct else ("choice_mismatch" if question.kind in CHOICE_QUESTION_KINDS else "answer_mismatch")
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
    record_learning_event(db, context, "question_answered", course_id=session.course_id,
                          question_id=question.id, payload={"correct": correct, "elapsed_seconds": payload.elapsed_seconds})
    db.commit()
    record_audit(db, context, "practice_attempt.submit", "question", str(question_id), {"correct": correct})
    db.commit()
    return {"id": attempt.id, "question_id": question_id, "correct": correct, "error_type": error_type}


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
    wrong_questions = []
    mastery_updates: dict[int, int] = {}
    for attempt in attempts:
        question_for_mastery = db.scalar(select(Question).where(Question.id == attempt.question_id, Question.tenant_id == context.tenant_id))
        if question_for_mastery and question_for_mastery.knowledge_point_id:
            point = db.scalar(select(KnowledgePoint).where(KnowledgePoint.id == question_for_mastery.knowledge_point_id, KnowledgePoint.tenant_id == context.tenant_id))
            if point is not None:
                point.practice_count += 1
                if attempt.correct:
                    point.correct_count += 1
                else:
                    point.wrong_count += 1
                point.last_studied_at = datetime.now()
                point.next_review_at = datetime.now() + timedelta(days=3 if attempt.correct else 1)
                # Explainable update: move 20% toward the observed result,
                # with a small difficulty adjustment for harder questions.
                target = 100 if attempt.correct else 0
                learning_rate = 0.24 if question_for_mastery.difficulty >= 4 else 0.20
                point.mastery = max(0, min(100, round(point.mastery * (1 - learning_rate) + target * learning_rate)))
                point.confidence = round(point.correct_count / point.practice_count, 4)
                mastery_updates[point.id] = point.mastery
        if attempt.correct is not False:
            continue
        question = question_for_mastery
        if question is None:
            continue
        wrong_questions.append({"question_id": question.id, "prompt": question.prompt,
                                "kind": question.kind, "error_type": ("choice_mismatch" if question.kind in CHOICE_QUESTION_KINDS else "answer_mismatch"),
                                "tags": question.tags})
        review = db.scalar(select(ReviewItem).where(ReviewItem.tenant_id == context.tenant_id, ReviewItem.question_id == question.id))
        if review is None:
            db.add(ReviewItem(tenant_id=context.tenant_id, question_id=question.id, title=question.prompt[:180],
                              status="reviewing", wrong_count=1,
                              error_reason=("choice_mismatch" if question.kind in CHOICE_QUESTION_KINDS else "answer_mismatch"),
                              ai_analysis=question.explanation or "本题答案与标准答案不一致，建议先复习关联知识点后再练习。",
                              next_review=date.today() + timedelta(days=1)))
        else:
            review.status = "reviewing"; review.wrong_count += 1; review.error_reason=("choice_mismatch" if question.kind in CHOICE_QUESTION_KINDS else "answer_mismatch"); review.ai_analysis = review.ai_analysis or question.explanation or "本题答案与标准答案不一致，建议先复习关联知识点后再练习。"; review.next_review = date.today() + timedelta(days=1)
    task_result = None
    if session.task_id is not None:
        task = db.scalar(select(StudyTask).where(StudyTask.id == session.task_id, StudyTask.tenant_id == context.tenant_id))
        answered_all = len({attempt.question_id for attempt in attempts}) >= session.total
        accuracy = (session.correct / session.total) if session.total else 0.0
        if task is not None and answered_all and accuracy >= 0.6:
            task.completed = True; task.status = "completed"; task.completed_at = datetime.now()
            record_learning_event(db, context, "task_completed_by_practice", course_id=task.course_id, task_id=task.id,
                                  payload={"practice_session_id": session.id, "accuracy": round(accuracy * 100, 1)})
            task_result = {"task_id": task.id, "completed": True, "accuracy": round(accuracy * 100, 1)}
        elif task is not None:
            task.status = "in_progress"
            task_result = {"task_id": task.id, "completed": False, "accuracy": round(accuracy * 100, 1), "reason": "answer every assigned question and reach 60% accuracy"}
    record_audit(db, context, "practice_session.complete", "practice_session", str(session.id), {"correct": session.correct})
    record_learning_event(db, context, "study_completed", course_id=session.course_id,
                          payload={"practice_session_id": session.id, "total": session.total,
                                   "correct": session.correct, "duration_seconds": session.duration_seconds})
    analysis_job = BackgroundJob(
        tenant_id=context.tenant_id, requested_by=context.user_id, job_type="ai_feature", status="queued",
        payload=json.dumps({"tenant_id": context.tenant_id, "feature": "learning_report", "data": {
            "course_id": session.course_id, "goal_id": session.seed, "start_date": date.today().isoformat(), "end_date": date.today().isoformat(),
            "request": f"分析刚完成的练习会话 {session.id}，给出薄弱知识点、题型建议和下一天复习计划。",
        }}, ensure_ascii=False), detail="queued automatic practice analysis",
    )
    db.add(analysis_job); db.flush()
    db.commit()
    accuracy = round(session.correct * 100 / session.total, 1) if session.total else 0
    return {"id": session.id, "status": session.status, "total": session.total, "correct": session.correct,
            "accuracy": accuracy, "analysis_job_id": analysis_job.id,
            "wrong_questions": wrong_questions, "knowledge_mastery": mastery_updates, "task_result": task_result}


@router.get("/reviews")
def list_reviews(context: CurrentContext, db: DbSession, due_only: bool = False, course_id: int | None = None) -> list[dict[str, object]]:
    statement = select(ReviewItem).where(ReviewItem.tenant_id == context.tenant_id, ReviewItem.status != "archived")
    if due_only:
        statement = statement.where(ReviewItem.next_review <= date.today(), ReviewItem.status != "mastered")
    if course_id is not None:
        statement = statement.where(ReviewItem.question_id.in_(select(Question.id).where(
            Question.course_id == course_id, Question.tenant_id == context.tenant_id,
        )))
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
        "ai_analysis": row.ai_analysis,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "last_reviewed_at": row.last_reviewed_at.isoformat() if row.last_reviewed_at else None,
    } for row in rows]


@router.get("/vocabulary")
def list_vocabulary(context: CurrentContext, db: DbSession, due_only: bool = False) -> list[dict[str, object]]:
    statement = select(ReviewItem).where(
        ReviewItem.tenant_id == context.tenant_id, ReviewItem.source == "vocabulary",
        ReviewItem.status != "archived",
    )
    if due_only:
        statement = statement.where(ReviewItem.next_review <= date.today(), ReviewItem.status != "mastered")
    rows = db.scalars(statement.order_by(ReviewItem.next_review, ReviewItem.id)).all()
    return [{"id": row.id, "word": row.title, "meaning": row.note.split("\n", 1)[0],
             "example": row.note.split("\n", 1)[1] if "\n" in row.note else "",
             "next_review": row.next_review.isoformat(), "status": row.status, "streak": row.streak}
            for row in rows]


@router.post("/vocabulary", status_code=status.HTTP_201_CREATED)
def create_vocabulary(payload: VocabularyRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    item = ReviewItem(tenant_id=context.tenant_id, title=payload.word.strip(),
                      note=f"{payload.meaning.strip()}\n{payload.example.strip()}".strip(),
                      source="vocabulary", status="new", next_review=date.today())
    db.add(item)
    record_audit(db, context, "vocabulary.create", "review_item", payload.word.strip())
    db.commit(); db.refresh(item)
    return {"id": item.id, "word": item.title, "next_review": item.next_review.isoformat()}


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
    item.last_reviewed_at = datetime.now()
    attempt = ReviewAttempt(
        tenant_id=context.tenant_id,
        review_item_id=item.id,
        result=payload.result,
        previous_streak=previous_streak,
        next_review=item.next_review,
    )
    db.add(attempt)
    record_audit(db, context, "review.submit", "review_item", str(item.id), {"result": payload.result})
    review_question = db.scalar(select(Question).where(Question.id == item.question_id, Question.tenant_id == context.tenant_id)) if item.question_id else None
    record_learning_event(db, context, "knowledge_reviewed" if item.question_id else "vocabulary_reviewed",
                          course_id=review_question.course_id if review_question else None,
                          question_id=item.question_id,
                          payload={"result": payload.result, "next_review": item.next_review.isoformat()})
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
def list_resources(context: CurrentContext, db: DbSession, course_id: int | None = None) -> list[dict[str, object]]:
    filters = [ResourceFile.tenant_id == context.tenant_id, ResourceFile.trashed.is_(False)]
    if course_id is not None:
        filters.append(ResourceFile.course_id == course_id)
    rows = db.scalars(
        select(ResourceFile)
        .where(*filters)
        .order_by(ResourceFile.id.desc())
    ).all()
    return [{"id": row.id, "name": row.name, "course_id": row.course_id, "size": row.size} for row in rows]


@router.post("/agent/sessions/{session_id}/resources/import-url", status_code=status.HTTP_202_ACCEPTED)
def import_agent_resource_url(
    session_id: int, payload: AgentResourceImportRequest, context: CurrentContext, db: DbSession,
) -> dict[str, object]:
    """Download an explicitly approved public search result into a course library."""
    if not payload.confirmed:
        raise HTTPException(status_code=409, detail="explicit confirmation is required")
    if db.scalar(select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try:
        with tempfile.TemporaryDirectory(prefix="learning-agent-import-") as folder:
            target = Path(folder) / "agent-resource"
            ResearchCurationService._download_public_file(payload.url.strip(), target)
            files = list(Path(folder).glob("agent-resource.*"))
            if len(files) != 1:
                raise ValueError("download did not produce a supported resource")
            source = files[0]
            content = source.read_bytes()
        settings = get_server_settings()
        if len(content) > settings.upload_max_bytes:
            raise ValueError("resource exceeds upload limit")
        digest = hashlib.sha256(content).hexdigest()
        duplicate = db.scalar(select(ResourceFile.id).where(
            ResourceFile.tenant_id == context.tenant_id, ResourceFile.sha256 == digest,
            ResourceFile.trashed.is_(False),
        ))
        if duplicate is not None:
            return {"resource_id": duplicate, "status": "already_exists"}
        filename = source.name.replace("agent-resource", "downloaded-resource")
        key = resource_key(tenant_id=context.tenant_id, resource_id=str(uuid4()), filename=filename)
        S3ObjectStorage(settings).put(key=key, stream=BytesIO(content), content_type="application/octet-stream")
        resource = ResourceFile(
            tenant_id=context.tenant_id, name=filename, original_name=filename,
            source_path=payload.url.strip(), relative_path=key, sha256=digest,
            size=len(content), course_id=payload.course_id,
        )
        job = BackgroundJob(
            tenant_id=context.tenant_id, requested_by=context.user_id,
            job_type="index_resource", status="queued", payload="{}",
            detail="queued by Agent-approved web resource import",
        )
        db.add_all([resource, job]); db.flush()
        pending = db.scalar(select(AgentHandoff).where(
            AgentHandoff.session_id == session_id, AgentHandoff.kind == "learning_pending",
        ).order_by(AgentHandoff.id.desc()))
        pending_payload = json.loads(pending.payload_json or "{}") if pending is not None else {}
        follow_up = None
        if pending_payload.get("status") == "completed" and int(pending_payload.get("course_id") or 0) == payload.course_id:
            follow_up = {"request": str(pending_payload.get("request") or "根据课程资料生成练习题"), "goal_id": pending_payload.get("goal_id"), "session_id": session_id, "vocabulary_count": pending_payload.get("vocabulary_count", 10)}
        job.payload = json.dumps({"resource_id": resource.id, "tenant_id": context.tenant_id, "question_follow_up": follow_up}, ensure_ascii=False)
        db.commit()
        return {"resource_id": resource.id, "job_id": job.id, "status": "queued", "filename": filename}
    except HTTPException:
        raise
    except Exception as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=f"resource import failed: {exc}") from exc


@router.post("/resources", status_code=status.HTTP_202_ACCEPTED)
def upload_resource(
    context: CurrentContext,
    db: DbSession,
    file: UploadFile = File(...),
    course_id: int | None = Form(default=None),
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
    if not set(payload.kinds) <= SUPPORTED_QUESTION_KINDS:
        raise HTTPException(status_code=422, detail="unsupported question kind")
    course = db.scalar(select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id))
    if course is None:
        raise HTTPException(status_code=404, detail="course not found")
    if payload.knowledge_point_id is not None and db.scalar(select(KnowledgePoint.id).where(
        KnowledgePoint.id == payload.knowledge_point_id,
        KnowledgePoint.course_id == payload.course_id,
        KnowledgePoint.tenant_id == context.tenant_id,
    )) is None:
        raise HTTPException(status_code=404, detail="knowledge point not found in course")
    if payload.resource_ids:
        resource_count = db.scalar(select(func.count()).select_from(ResourceFile).where(
            ResourceFile.id.in_(payload.resource_ids), ResourceFile.tenant_id == context.tenant_id,
            ResourceFile.course_id == payload.course_id, ResourceFile.trashed.is_(False),
        )) or 0
        if resource_count != len(set(payload.resource_ids)):
            raise HTTPException(status_code=404, detail="one or more resources not found in course")
    job = BackgroundJob(
        tenant_id=context.tenant_id,
        requested_by=context.user_id,
        job_type="generate_questions",
        status="queued",
        payload=json.dumps({"tenant_id": context.tenant_id, "course_id": payload.course_id,
                            "knowledge_point_id": payload.knowledge_point_id,
                            "resource_ids": list(dict.fromkeys(payload.resource_ids)),
                            "request": payload.request, "count": payload.count,
                            "difficulty": payload.difficulty, "kinds": payload.kinds}, ensure_ascii=False),
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
    if payload.resource_ids and payload.feature != "knowledge_extraction":
        raise HTTPException(status_code=422, detail="resource_ids is only supported for knowledge extraction")
    if payload.resource_ids and payload.course_id is None:
        raise HTTPException(status_code=422, detail="course_id is required when resource_ids are provided")
    course_id = payload.course_id
    if course_id is not None and db.scalar(select(Course.id).where(Course.id == course_id, Course.tenant_id == context.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="course not found")
    resource_ids = list(dict.fromkeys(payload.resource_ids))
    if resource_ids:
        resource_count = db.scalar(select(func.count()).select_from(ResourceFile).where(
            ResourceFile.id.in_(resource_ids), ResourceFile.tenant_id == context.tenant_id,
            ResourceFile.course_id == course_id, ResourceFile.trashed.is_(False),
        )) or 0
        if resource_count != len(resource_ids):
            raise HTTPException(status_code=404, detail="one or more resources not found in course")
    data = payload.model_dump(mode="json")
    data.pop("feature")
    data["resource_ids"] = resource_ids
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


@router.get("/agent/tools/search")
def search_agent_tools(context: CurrentContext, q: str = "", limit: int = 8) -> list[dict[str, object]]:
    """Discover relevant capability metadata without injecting the full catalog."""
    if limit < 1 or limit > 20:
        raise HTTPException(status_code=422, detail="limit must be between 1 and 20")
    return search_capabilities(q, client="web", limit=limit)


@router.get("/agent/memories")
def list_agent_memories(context: CurrentContext, db: DbSession, course_id: int | None = None) -> list[dict[str, object]]:
    statement = select(AgentMemory).where(
        AgentMemory.tenant_id == context.tenant_id,
        AgentMemory.confirmed.is_(True), AgentMemory.deleted.is_(False),
    )
    if course_id is not None:
        statement = statement.where((AgentMemory.course_id.is_(None)) | (AgentMemory.course_id == course_id))
    rows = db.scalars(statement.order_by(AgentMemory.updated_at.desc())).all()
    return [{"id": item.id, "scope": item.scope, "category": item.category, "course_id": item.course_id, "content": json.loads(item.content_json or "{}"), "updated_at": item.updated_at.isoformat()} for item in rows]


@router.post("/agent/sessions/{session_id}/learning-launch", status_code=status.HTTP_202_ACCEPTED)
def launch_learning_loop(session_id: int, payload: LearningLaunchRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    """Atomically create a goal and queue its plan/questions from one Agent action."""
    from app.models import AgentSession
    session = db.scalar(select(AgentSession).where(AgentSession.id == session_id, AgentSession.tenant_id == context.tenant_id))
    if session is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    course_id = payload.course_id
    course_created = False
    if course_id is not None and db.scalar(select(Course.id).where(Course.id == course_id, Course.tenant_id == context.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="course not found")
    if course_id is None:
        course_name = _course_title_from_request(payload.request)
        course = db.scalar(select(Course).where(
            Course.tenant_id == context.tenant_id,
            Course.name == course_name,
            Course.subject == "AI 自动创建",
        ).order_by(Course.id.desc()))
        if course is None:
            course = Course(tenant_id=context.tenant_id, name=course_name,
                            subject="AI 自动创建", description=payload.request[:10000])
            db.add(course); db.flush(); course_created = True
        course_id = course.id
    target = payload.target_date or (date.today() + timedelta(days=30))
    if target < date.today():
        raise HTTPException(status_code=422, detail="target_date cannot be in the past")
    pending = db.scalar(select(AgentHandoff).where(
        AgentHandoff.session_id == session_id, AgentHandoff.kind == "learning_pending",
    ).order_by(AgentHandoff.id.desc()))
    source_items: list[dict[str, object]] = []
    if pending is not None:
        stored = json.loads(pending.payload_json or "{}")
        if stored.get("status") == "completed":
            raise HTTPException(status_code=409, detail="this learning request has already started")
        source_items = list(stored.get("source_items") or [])
        # The handoff is later used when imported material finishes indexing.
        # Persist the resolved course so that follow-up question generation is
        # attached to an automatically created course as well.
        stored.update({"status": "completed", "course_id": course_id, "started_at": datetime.now().isoformat()})
        pending.payload_json = json.dumps(stored, ensure_ascii=False)
    goal = StudyGoal(tenant_id=context.tenant_id, title=payload.title.strip(), course_id=course_id,
                     target_date=target, weekly_minutes=payload.weekly_minutes)
    db.add(goal); db.flush()
    if pending is not None:
        stored = json.loads(pending.payload_json or "{}")
        stored["goal_id"] = goal.id
        stored["vocabulary_count"] = payload.vocabulary_count
        pending.payload_json = json.dumps(stored, ensure_ascii=False)
    # Fixed workflow: the question agent may only run after the research agent
    # has brought relevant material into the indexed course library.
    indexed_evidence = db.scalar(select(func.count()).select_from(DocumentChunk).where(
        DocumentChunk.tenant_id == context.tenant_id, DocumentChunk.course_id == course_id,
    )) or 0
    # Planning uses the learner's goal, task history and mastery snapshot. It
    # must not wait for a document upload; only generated questions require
    # indexed evidence.
    plan_job = None
    if indexed_evidence:
        plan_job = BackgroundJob(tenant_id=context.tenant_id, requested_by=context.user_id, job_type="ai_feature", status="queued",
            payload=json.dumps({"tenant_id": context.tenant_id, "feature": "learning_plan", "data": {"goal_id": goal.id, "course_id": course_id, "request": payload.request}}, ensure_ascii=False), detail="queued by task-scheduling agent")
        db.add(plan_job); db.flush()
    question_job_id = None
    vocabulary_job_id = None
    if indexed_evidence:
        question_job = BackgroundJob(tenant_id=context.tenant_id, requested_by=context.user_id, job_type="generate_questions", status="queued",
            payload=json.dumps({"tenant_id": context.tenant_id, "course_id": course_id, "request": payload.request, "count": payload.question_count, "difficulty": 3, "kinds": ["single_choice", "short_answer"], "auto_practice": True, "goal_id": goal.id, "agent_session_id": session_id}, ensure_ascii=False), detail="queued by question agent from indexed course materials")
        db.add(question_job); db.flush(); question_job_id = question_job.id
        # Vocabulary extraction requires indexed course material. It is not a
        # prerequisite for a learner asking to create a plan, so do not queue
        # a guaranteed-failing job for a newly created or empty course.
    record_audit(db, context, "agent.learning_launch", "study_goal", str(goal.id), {"plan_job_id": plan_job.id if plan_job else None, "question_job_id": question_job_id})
    db.add(AgentHandoff(session_id=session_id, kind="active_course", target_id=course_id,
                        payload_json=json.dumps({"course_id": course_id}, ensure_ascii=False)))
    db.commit()
    return {"course_id": course_id, "course_created": course_created, "goal_id": goal.id, "plan_job_id": plan_job.id if plan_job else None, "question_job_id": question_job_id, "vocabulary_job_id": vocabulary_job_id, "source_items": source_items,
            "target_date": target.isoformat(), "status": "queued", "workflow_steps": [
                {"agent": "资料检索 Agent", "status": "ready", "detail": "检索并筛选高相关学习资料；导入需你确认"},
                {"agent": "任务编排 Agent", "status": "queued" if plan_job else "waiting_for_material", "detail": "资料索引并生成可直接作答的题目后，再生成每日任务"},
                {"agent": "出题 Agent", "status": "queued" if question_job_id else "waiting_for_material", "detail": "依据已索引资料出题"},
            ]}


@router.post("/agent/sessions/{session_id}/diagnostic-launch", status_code=status.HTTP_202_ACCEPTED)
def launch_diagnostic_practice(session_id: int, payload: DiagnosticLaunchRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    from app.models import AgentSession
    if db.scalar(select(AgentSession.id).where(AgentSession.id == session_id, AgentSession.tenant_id == context.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    course_id = payload.course_id
    course_created = False
    if course_id is not None and db.scalar(select(Course.id).where(Course.id == course_id, Course.tenant_id == context.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="course not found")
    if course_id is None:
        course = Course(tenant_id=context.tenant_id, name=_course_title_from_request(payload.request), subject="AI 自动创建", description=payload.request[:10000])
        db.add(course); db.flush(); course_id = course.id; course_created = True
    job = BackgroundJob(tenant_id=context.tenant_id, requested_by=context.user_id, job_type="generate_questions", status="queued",
        payload=json.dumps({"tenant_id": context.tenant_id, "course_id": course_id, "request": payload.request,
                            "count": payload.count, "difficulty": 3, "kinds": ["single_choice", "short_answer"],
                            "auto_practice": True, "allow_ungrounded": True, "agent_session_id": session_id}, ensure_ascii=False), detail="queued diagnostic practice")
    db.add(job); db.commit(); db.refresh(job)
    db.add(AgentHandoff(session_id=session_id, kind="active_course", target_id=course_id,
                        payload_json=json.dumps({"course_id": course_id}, ensure_ascii=False)))
    db.commit()
    return {"job_id": job.id, "course_id": course_id, "course_created": course_created, "status": "queued", "mode": "diagnostic"}


@router.post("/agent/sessions/{session_id}/tools")
def execute_agent_tool(session_id: int, payload: AgentToolRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    from app.models import AgentSession, AgentToolCall
    session = db.scalar(select(AgentSession).where(AgentSession.id == session_id, AgentSession.tenant_id == context.tenant_id))
    if session is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    tool_name = payload.tool_name.strip()
    arguments = dict(payload.arguments)
    declared = {str(item["name"]): item for item in tools_for_client("web")}
    if tool_name not in declared:
        raise HTTPException(status_code=422, detail="tool is not available to the Web Agent")
    if bool(declared[tool_name].get("requires_confirmation")) and not payload.confirmed:
        raise HTTPException(status_code=409, detail="tool requires explicit confirmation")
    call = AgentToolCall(session_id=session_id, tool_name=tool_name, status="running", detail="executed by Web Agent")
    call.input_json = json.dumps(arguments, ensure_ascii=False)
    db.add(call); db.commit(); db.refresh(call)
    try:
        call_status = "completed"
        if tool_name == "learning_data.read_snapshot":
            raw_course_id = arguments.get("course_id")
            course_id = int(raw_course_id) if raw_course_id is not None else None
            result = learning_snapshot(db, context.tenant_id, course_id)
        elif tool_name == "agent.create_goal":
            goal_request = GoalRequest.model_validate(arguments)
            if goal_request.target_date < date.today():
                raise ValueError("goal target date cannot be in the past")
            if goal_request.course_id is not None and db.scalar(
                select(Course.id).where(Course.id == goal_request.course_id, Course.tenant_id == context.tenant_id)
            ) is None:
                raise ValueError("course not found")
            goal = StudyGoal(
                tenant_id=context.tenant_id, title=goal_request.title.strip(),
                target_date=goal_request.target_date, target_score=goal_request.target_score,
                weekly_minutes=goal_request.weekly_minutes, course_id=goal_request.course_id,
            )
            db.add(goal); db.flush()
            record_audit(db, context, "agent.goal.create", "study_goal", str(goal.id))
            result = {"goal_id": goal.id, "title": goal.title, "target_date": goal.target_date.isoformat()}
        elif tool_name in {"agent.generate_plan", "agent.generate_report"}:
            feature = "learning_plan" if tool_name == "agent.generate_plan" else "learning_report"
            if feature == "learning_plan" and arguments.get("goal_id") is None:
                raise ValueError("goal_id is required to generate a learning plan")
            job = BackgroundJob(
                tenant_id=context.tenant_id, requested_by=context.user_id, job_type="ai_feature", status="queued",
                payload=json.dumps({"tenant_id": context.tenant_id, "feature": feature, "data": arguments}, ensure_ascii=False),
                detail=f"queued by {tool_name}",
            )
            db.add(job); db.flush()
            record_audit(db, context, f"{tool_name}.queue", "background_job", str(job.id))
            result = {"job_id": str(job.id), "status": "queued", "feature": feature}
        elif tool_name == "agent.start_workflow":
            course_id = int(arguments.get("course_id", 0))
            if not course_id or db.scalar(select(Course.id).where(Course.id == course_id, Course.tenant_id == context.tenant_id)) is None:
                raise ValueError("a course owned by this workspace is required")
            resources = list(db.scalars(select(ResourceFile.id).where(ResourceFile.course_id == course_id, ResourceFile.tenant_id == context.tenant_id, ResourceFile.trashed.is_(False))))
            if not resources:
                raise ValueError("the selected course has no available resources")
            workflow = AgentWorkflow(
                tenant_id=context.tenant_id, session_id=session_id, course_id=course_id,
                request=str(arguments.get("request", "")).strip() or "Complete the learning workflow from course resources.",
                context_json=json.dumps({"resource_ids": resources}, ensure_ascii=False),
            )
            db.add(workflow); db.flush()
            record_audit(db, context, "agent.workflow.create", "agent_workflow", str(workflow.id))
            result = {"workflow_id": workflow.id, "status": workflow.status, "current_step": workflow.current_step}
        elif tool_name == "agent.remember":
            memory_request = AgentMemoryRequest.model_validate({**arguments, "confirmed": True})
            if memory_request.scope == "course" and memory_request.course_id is None:
                raise ValueError("course_id is required for course memory")
            if memory_request.course_id is not None and db.scalar(select(Course.id).where(Course.id == memory_request.course_id, Course.tenant_id == context.tenant_id)) is None:
                raise ValueError("course not found")
            memory = AgentMemory(
                tenant_id=context.tenant_id, scope=memory_request.scope, category=memory_request.category,
                course_id=memory_request.course_id, content_json=json.dumps(memory_request.content, ensure_ascii=False),
                confirmed=True, source="agent_tool",
            )
            db.add(memory); db.flush()
            record_audit(db, context, "agent.memory.create", "agent_memory", str(memory.id))
            result = {"memory_id": memory.id, "scope": memory.scope, "category": memory.category}
        elif tool_name.startswith("desktop."):
            companion_id = str(arguments.get("companion_id", "")).strip()
            if not companion_id or len(companion_id) > 120:
                raise ValueError("companion_id is required for a desktop tool")
            # A companion is an authenticated desktop client polling this
            # durable call. The SaaS host never obtains local file access.
            result = {"command_id": call.id, "companion_id": companion_id, "status": "queued"}
            call_status = "queued"
            call.detail = f"queued for desktop companion {companion_id}"
        else:
            result = WebAgentToolExecutor(tenant_id=context.tenant_id, session_id=session_id).execute(tool_name, arguments)
        call.status = call_status; call.output_json = json.dumps(result, ensure_ascii=False)
        call.finished_at = datetime.now() if call_status == "completed" else None
        db.commit()
        return {"tool_name": tool_name, "call_id": call.id, "status": call.status, "result": result}
    except Exception as exc:
        call.status = "failed"; call.error_message = str(exc); call.finished_at = datetime.now(); db.commit()
        raise HTTPException(status_code=502, detail=f"tool execution failed: {exc}") from exc


@router.get("/desktop-companion/commands")
def poll_desktop_companion_commands(
    companion_id: str, context: CurrentContext, db: DbSession, limit: int = 10,
) -> list[dict[str, object]]:
    """Claim queued Web Agent calls for one authenticated desktop companion."""
    from app.models import AgentSession, AgentToolCall
    if not companion_id.strip() or len(companion_id) > 120:
        raise HTTPException(status_code=422, detail="invalid companion_id")
    # A desktop can exit after claiming a call. Requeue only calls whose claim
    # lease has expired; ``finished_at`` temporarily stores the claim time.
    stale_before = datetime.now() - timedelta(minutes=2)
    stale_rows = db.scalars(
        select(AgentToolCall)
        .join(AgentSession, AgentSession.id == AgentToolCall.session_id)
        .where(
            AgentSession.tenant_id == context.tenant_id,
            AgentToolCall.status == "running",
            AgentToolCall.tool_name.like("desktop.%"),
            AgentToolCall.finished_at.is_not(None), AgentToolCall.finished_at < stale_before,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for stale in stale_rows:
        stale.status = "queued"
        stale.detail = "desktop companion claim expired; requeued"
        stale.finished_at = None
    if stale_rows:
        db.flush()
    rows = db.scalars(
        select(AgentToolCall)
        .join(AgentSession, AgentSession.id == AgentToolCall.session_id)
        .where(
            AgentSession.tenant_id == context.tenant_id,
            AgentToolCall.status == "queued",
            AgentToolCall.tool_name.like("desktop.%"),
        )
        .order_by(AgentToolCall.id)
        # Read a slightly wider window because commands for other desktop
        # installations share the tenant queue. Only matching calls are
        # claimed below.
        .limit(200)
        .with_for_update(skip_locked=True)
    ).all()
    commands: list[dict[str, object]] = []
    for call in rows:
        if len(commands) >= max(1, min(limit, 50)):
            break
        try:
            arguments = json.loads(call.input_json or "{}")
        except json.JSONDecodeError:
            arguments = {}
        if not isinstance(arguments, dict) or str(arguments.get("companion_id", "")).strip() != companion_id:
            continue
        # companion_id is routing metadata, never passed into an MCP tool.
        arguments.pop("companion_id", None)
        call.status = "running"
        call.detail = f"claimed by desktop companion {companion_id}"
        call.finished_at = datetime.now()
        commands.append({"command_id": call.id, "tool_name": call.tool_name, "arguments": arguments, "confirmed": True})
    if commands or stale_rows:
        db.commit()
    return commands


@router.post("/desktop-companion/commands/{command_id}/result")
def complete_desktop_companion_command(
    command_id: int, payload: dict[str, object], context: CurrentContext, db: DbSession,
) -> dict[str, object]:
    """Persist a desktop execution result in the originating Agent audit log."""
    from app.models import AgentSession, AgentToolCall
    call = db.scalar(
        select(AgentToolCall)
        .join(AgentSession, AgentSession.id == AgentToolCall.session_id)
        .where(
            AgentToolCall.id == command_id,
            AgentSession.tenant_id == context.tenant_id,
            AgentToolCall.status == "running",
            AgentToolCall.tool_name.like("desktop.%"),
        )
    )
    if call is None:
        raise HTTPException(status_code=404, detail="desktop command not found or no longer active")
    companion_id = str(payload.get("companion_id", "")).strip()
    try:
        input_data = json.loads(call.input_json or "{}")
    except json.JSONDecodeError:
        input_data = {}
    if not companion_id or not isinstance(input_data, dict) or input_data.get("companion_id") != companion_id:
        raise HTTPException(status_code=403, detail="command was not claimed by this companion")
    error = str(payload.get("error", "")).strip()[:4000]
    output = payload.get("result", {})
    call.status = "failed" if error else "completed"
    call.error_message = error
    call.output_json = json.dumps(output, ensure_ascii=False, default=str)
    call.detail = "desktop companion execution failed" if error else "desktop companion execution completed"
    call.finished_at = datetime.now()
    db.commit()
    return {"command_id": call.id, "status": call.status}


@router.get("/agent/sessions/{session_id}/tool-calls")
def list_agent_tool_calls(session_id: int, context: CurrentContext, db: DbSession) -> list[dict[str, object]]:
    from app.models import AgentSession, AgentToolCall
    session = db.scalar(select(AgentSession).where(AgentSession.id == session_id, AgentSession.tenant_id == context.tenant_id))
    if session is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    rows = db.scalars(select(AgentToolCall).where(AgentToolCall.session_id == session_id).order_by(AgentToolCall.id)).all()
    result: list[dict[str, object]] = []
    for item in rows:
        try:
            input_data = json.loads(item.input_json or "{}")
        except json.JSONDecodeError:
            input_data = {}
        try:
            output_data = json.loads(item.output_json or "{}")
        except json.JSONDecodeError:
            output_data = {}
        result.append({
            "id": item.id, "tool_name": item.tool_name, "status": item.status,
            "detail": item.detail, "input": input_data, "output": output_data,
            "error": item.error_message, "created_at": item.created_at.isoformat(),
            "finished_at": item.finished_at.isoformat() if item.finished_at else None,
        })
    return result


@router.post("/agent/memories", status_code=status.HTTP_201_CREATED)
def create_agent_memory(payload: AgentMemoryRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    if not payload.confirmed:
        raise HTTPException(status_code=409, detail="Memory requires explicit user confirmation")
    if payload.scope == "course" and payload.course_id is None:
        raise HTTPException(status_code=422, detail="course memory requires course_id")
    if payload.course_id is not None and db.scalar(select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="course not found")
    item = AgentMemory(tenant_id=context.tenant_id, scope=payload.scope, category=payload.category, course_id=payload.course_id, content_json=json.dumps(payload.content, ensure_ascii=False), confirmed=True, source="web_confirmed")
    db.add(item); db.commit(); db.refresh(item)
    return {"id": item.id, "scope": item.scope, "category": item.category, "course_id": item.course_id, "content": payload.content, "updated_at": item.updated_at.isoformat()}


@router.delete("/agent/memories/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_agent_memory(memory_id: int, context: CurrentContext, db: DbSession) -> None:
    item = db.scalar(select(AgentMemory).where(AgentMemory.id == memory_id, AgentMemory.tenant_id == context.tenant_id, AgentMemory.deleted.is_(False)))
    if item is None:
        raise HTTPException(status_code=404, detail="memory not found")
    item.deleted = True
    db.commit()


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


@router.get("/agent/sessions/{session_id}/learning-launch-state")
def get_learning_launch_state(session_id: int, context: CurrentContext, db: DbSession) -> dict[str, object]:
    """Return the durable confirmation state used to restore the learning card."""
    from app.models import AgentSession
    session = db.scalar(select(AgentSession).where(
        AgentSession.id == session_id, AgentSession.tenant_id == context.tenant_id,
    ))
    if session is None:
        raise HTTPException(status_code=404, detail="agent session not found")
    handoff = db.scalar(select(AgentHandoff).where(
        AgentHandoff.session_id == session_id, AgentHandoff.kind == "learning_pending",
    ).order_by(AgentHandoff.id.desc()))
    if handoff is None:
        return {"state": None}
    try:
        payload = json.loads(handoff.payload_json or "{}")
    except json.JSONDecodeError:
        payload = {}
    return {"state": payload}


@router.post("/agent/sessions/{session_id}/messages/stream")
def stream_agent_message(session_id: int, payload: AgentMessageRequest, context: CurrentContext, db: DbSession):
    if payload.course_id is not None and db.scalar(select(Course.id).where(Course.id == payload.course_id, Course.tenant_id == context.tenant_id)) is None:
        raise HTTPException(status_code=404, detail="course not found")
    try: session_messages(db, context.tenant_id, session_id)
    except ValueError as exc: raise HTTPException(status_code=404, detail=str(exc)) from exc
    return StreamingResponse(
        stream_agent_reply(session_factory=session_factory(get_server_settings()), tenant_id=context.tenant_id, user_id=context.user_id, session_id=session_id, message=payload.message.strip(), course_id=payload.course_id, event_type=payload.event_type, event_payload=payload.event_payload),
        media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/agent/sessions/{session_id}/coding/proposals")
def create_web_coding_proposal(session_id: int, payload: AgentMessageRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    _ensure_web_coding_enabled()
    try:
        session_messages(db, context.tenant_id, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    settings = get_ai_settings()
    if not settings.enabled or not settings.api_key.strip():
        raise HTTPException(status_code=503, detail="Coding Agent model is not configured")
    snapshot = learning_snapshot(db, context.tenant_id, payload.course_id)
    try:
        proposal = propose_web_code(model=create_chat_model(settings), request=payload.message, payload={"learning_snapshot": snapshot})
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Coding Agent could not prepare a safe proposal: {exc}") from exc
    handoff = AgentHandoff(session_id=session_id, kind="web_coding_proposal", payload_json=json.dumps({
        "status": "proposed", "request": payload.message, "proposal": proposal.model_dump(),
        "payload": {"learning_snapshot": snapshot},
    }, ensure_ascii=False))
    db.add(handoff); db.commit(); db.refresh(handoff)
    return {"id": handoff.id, "status": "proposed", "proposal": proposal.model_dump(exclude={"skill_script"})}


@router.post("/agent/sessions/{session_id}/coding/proposals/{handoff_id}/run")
def run_web_coding_proposal(session_id: int, handoff_id: int, payload: WebCodingRunRequest, context: CurrentContext, db: DbSession) -> dict[str, object]:
    _ensure_web_coding_enabled()
    if not payload.confirmed:
        raise HTTPException(status_code=409, detail="confirm running the temporary sandbox code")
    try:
        session_messages(db, context.tenant_id, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    handoff = db.scalar(select(AgentHandoff).where(AgentHandoff.id == handoff_id, AgentHandoff.session_id == session_id, AgentHandoff.kind == "web_coding_proposal"))
    if handoff is None:
        raise HTTPException(status_code=404, detail="Coding proposal not found")
    stored = json.loads(handoff.payload_json or "{}")
    if stored.get("status") == "completed":
        return {"id": handoff.id, **stored}
    try:
        proposal = MetaCodeProposal.model_validate(stored["proposal"])
        result = run_web_code(proposal=proposal, payload=dict(stored.get("payload") or {}), tenant_id=context.tenant_id, session_id=session_id)
    except Exception as exc:
        stored.update({"status": "failed", "error": str(exc)[:2000]})
        handoff.payload_json = json.dumps(stored, ensure_ascii=False); db.commit()
        raise HTTPException(status_code=422, detail=f"Coding Agent execution failed: {exc}") from exc
    stored.update({"status": "completed" if result["returncode"] == 0 else "failed", "result": result})
    handoff.payload_json = json.dumps(stored, ensure_ascii=False); db.commit()
    return {"id": handoff.id, "status": stored["status"], "result": result,
            "summary": "Temporary Coding Agent task completed." if result["returncode"] == 0 else "Temporary code finished with errors."}


@router.get("/agent/sessions/{session_id}/coding/proposals/latest")
def latest_web_coding_proposal(session_id: int, context: CurrentContext, db: DbSession) -> dict[str, object]:
    try:
        session_messages(db, context.tenant_id, session_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    handoff = db.scalar(select(AgentHandoff).where(
        AgentHandoff.session_id == session_id, AgentHandoff.kind == "web_coding_proposal",
    ).order_by(AgentHandoff.id.desc()))
    if handoff is None:
        return {"status": "not_found"}
    stored = json.loads(handoff.payload_json or "{}")
    proposal = dict(stored.get("proposal") or {})
    proposal.pop("skill_script", None)
    return {"id": handoff.id, "status": stored.get("status", "proposed"), "proposal": proposal, "result": stored.get("result"), "error": stored.get("error", "")}


@router.get("/agent/sessions/{session_id}/downloads/{handoff_id}")
def download_agent_report(session_id: int, handoff_id: int, context: CurrentContext, db: DbSession) -> Response:
    from app.models import AgentHandoff, AgentSession
    session = db.scalar(select(AgentSession).where(AgentSession.id == session_id, AgentSession.tenant_id == context.tenant_id))
    handoff = db.scalar(select(AgentHandoff).where(AgentHandoff.id == handoff_id, AgentHandoff.session_id == session_id, AgentHandoff.kind == "downloadable_report"))
    if session is None or handoff is None:
        raise HTTPException(status_code=404, detail="download not found")
    try:
        payload = json.loads(handoff.payload_json)
        content = S3ObjectStorage(get_server_settings()).get_bytes(key=str(payload["key"]))
        filename = str(payload.get("filename", "learning-report.md")).replace('"', "")
    except Exception as exc:
        raise HTTPException(status_code=503, detail="report file is unavailable") from exc
    return Response(content=content, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": f'attachment; filename="{filename}"'})


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
