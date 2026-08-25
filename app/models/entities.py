from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


class Course(Base):
    __tablename__ = "courses"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(120), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    education_stage: Mapped[str] = mapped_column(String(40), default="大学")
    grade_level: Mapped[str] = mapped_column(String(40), default="")
    subject: Mapped[str] = mapped_column(String(60), default="其他")
    exam_type: Mapped[str] = mapped_column(String(60), default="")
    textbook_version: Mapped[str] = mapped_column(String(80), default="")
    target_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    target_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    color_tag: Mapped[str] = mapped_column(String(20), default="#155EEF")
    source: Mapped[str] = mapped_column(String(20), default="user")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_opened_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CourseNote(Base):
    __tablename__ = "course_notes"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    title: Mapped[str] = mapped_column(String(160), default="学习笔记")
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class StudyTask(Base):
    __tablename__ = "study_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(160), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    knowledge_point_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id"), nullable=True, index=True)
    task_type: Mapped[str] = mapped_column(String(30), default="学习")
    planned_date: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=30)
    priority: Mapped[str] = mapped_column(String(20), default="中")
    scheduled_time: Mapped[str] = mapped_column(String(5), default="")
    note: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="user")
    recurrence_key: Mapped[str] = mapped_column(String(80), default="")
    status: Mapped[str] = mapped_column(String(20), default="planned", index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Question(Base):
    __tablename__ = "questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    knowledge_point_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id"), nullable=True)
    kind: Mapped[str] = mapped_column(String(20), default="单选")
    prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[str] = mapped_column(String(300), default="")
    options: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="user")
    difficulty: Mapped[int] = mapped_column(Integer, default=3)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)


class ReviewItem(Base):
    __tablename__ = "review_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), nullable=True)
    title: Mapped[str] = mapped_column(String(180))
    status: Mapped[str] = mapped_column(String(20), default="new")
    streak: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=1)
    next_review: Mapped[date] = mapped_column(Date, default=date.today, index=True)
    note: Mapped[str] = mapped_column(Text, default="")
    error_reason: Mapped[str] = mapped_column(String(300), default="")
    ai_analysis: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    last_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="user")


class ResourceFile(Base):
    __tablename__ = "resource_files"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    name: Mapped[str] = mapped_column(String(255))
    original_name: Mapped[str] = mapped_column(String(255), default="")
    source_path: Mapped[str] = mapped_column(String(1000), default="")
    relative_path: Mapped[str] = mapped_column(String(500), unique=True)
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    size: Mapped[int] = mapped_column(Integer)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    tags: Mapped[str] = mapped_column(String(500), default="")
    trashed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class KnowledgePoint(Base):
    __tablename__ = "knowledge_points"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    name: Mapped[str] = mapped_column(String(160), index=True)
    mastery: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(30), default="概念")
    definition: Mapped[str] = mapped_column(Text, default="")
    formula: Mapped[str] = mapped_column(Text, default="")
    prerequisites_json: Mapped[str] = mapped_column(Text, default="[]")
    related_points_json: Mapped[str] = mapped_column(Text, default="[]")
    common_mistakes_json: Mapped[str] = mapped_column(Text, default="[]")
    difficulty: Mapped[int] = mapped_column(Integer, default=3)
    importance: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    practice_count: Mapped[int] = mapped_column(Integer, default=0)
    correct_count: Mapped[int] = mapped_column(Integer, default=0)
    wrong_count: Mapped[int] = mapped_column(Integer, default=0)
    last_studied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    next_review_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="user")
    vector_id: Mapped[str | None] = mapped_column(
        String(100), nullable=True, unique=True
    )
    embedding_model: Mapped[str] = mapped_column(String(160), default="")


class PracticeSession(Base):
    __tablename__ = "practice_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total: Mapped[int] = mapped_column(Integer, default=0)
    correct: Mapped[int] = mapped_column(Integer, default=0)
    duration_seconds: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="running")
    seed: Mapped[int | None] = mapped_column(Integer, nullable=True)


class QuestionAttempt(Base):
    __tablename__ = "question_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("practice_sessions.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    response: Mapped[str] = mapped_column(Text, default="")
    correct: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, default=0)
    attempted_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class PracticeSessionQuestion(Base):
    __tablename__ = "practice_session_questions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("practice_sessions.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    marked: Mapped[bool] = mapped_column(Boolean, default=False)


class ReviewAttempt(Base):
    __tablename__ = "review_attempts"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    review_item_id: Mapped[int] = mapped_column(ForeignKey("review_items.id"), index=True)
    result: Mapped[str] = mapped_column(String(20))
    previous_streak: Mapped[int] = mapped_column(Integer, default=0)
    next_review: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class LearningEvent(Base):
    """Canonical event stream for analytics and adaptive planning."""
    __tablename__ = "learning_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    event_type: Mapped[str] = mapped_column(String(60), index=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True, index=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("study_tasks.id"), nullable=True, index=True)
    question_id: Mapped[int | None] = mapped_column(ForeignKey("questions.id"), nullable=True, index=True)
    knowledge_point_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id"), nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    occurred_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class StudySession(Base):
    __tablename__ = "study_sessions"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    task_id: Mapped[int | None] = mapped_column(ForeignKey("study_tasks.id"), nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=0)
    note: Mapped[str] = mapped_column(Text, default="")


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)


class ToolCallLog(Base):
    __tablename__ = "tool_call_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tool_name: Mapped[str] = mapped_column(String(120), index=True)
    arguments: Mapped[str] = mapped_column(Text, default="{}")
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    result_summary: Mapped[str] = mapped_column(Text, default="")
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)
    audit_id: Mapped[str] = mapped_column(String(40), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    action: Mapped[str] = mapped_column(String(120), index=True)
    target_type: Mapped[str] = mapped_column(String(80), default="")
    target_id: Mapped[str] = mapped_column(String(80), default="")
    detail: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class BackgroundJob(Base):
    __tablename__ = "background_jobs"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    job_type: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    detail: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class StudyGoal(Base):
    __tablename__ = "study_goals"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(160))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    target_date: Mapped[date] = mapped_column(Date, index=True)
    target_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    weekly_minutes: Mapped[int] = mapped_column(Integer, default=420)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class TaskRecurrence(Base):
    __tablename__ = "task_recurrences"
    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("study_tasks.id"), unique=True)
    frequency: Mapped[str] = mapped_column(String(20), default="none")
    interval: Mapped[int] = mapped_column(Integer, default=1)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
