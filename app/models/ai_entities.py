from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base

class DocumentIndex(Base):
    """一份资料当前的解析与索引状态。"""
    __tablename__ = "document_indexes"

    __table_args__ = (
        UniqueConstraint(
            "resource_id",
            "parser_version",
            "chunker_version",
            "embedding_model",
            name="uq_document_index_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resource_files.id"),
        index=True,
    )

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True,
    )

    parser_version: Mapped[str] = mapped_column(String(40))
    chunker_version: Mapped[str] = mapped_column(String(40))
    embedding_model: Mapped[str] = mapped_column(String(160))

    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    chunk_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        onupdate=datetime.now,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )


class DocumentChunk(Base):
    """可检索、可引用的资料文本片段。"""

    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint(
            "document_index_id",
            "chunk_number",
            name="uq_document_chunk_number",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    document_index_id: Mapped[int] = mapped_column(
        ForeignKey("document_indexes.id", ondelete="CASCADE"),
        index=True,
    )
    resource_id: Mapped[int] = mapped_column(
        ForeignKey("resource_files.id"),
        index=True,
    )
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id"),
        nullable=True,
        index=True,
    )

    chunk_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64), index=True)

    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    line_end: Mapped[int | None] = mapped_column(Integer, nullable=True)

    section_title: Mapped[str] = mapped_column(String(500), default="")
    location_label: Mapped[str] = mapped_column(String(300), default="")
    metadata_json: Mapped[str] = mapped_column(Text, default="{}")

    vector_id: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
        unique=True,
    )
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
    )


class AIRun(Base):
    """一次模型调用或 AI 工作流执行记录。"""

    __tablename__ = "ai_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # The initiating member is retained separately from tenant scope so
    # organization owners can audit consumption without exposing prompts.
    user_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    run_uuid: Mapped[str] = mapped_column(
        String(36),
        unique=True,
        index=True,
    )

    feature: Mapped[str] = mapped_column(String(50), index=True)
    status: Mapped[str] = mapped_column(
        String(20),
        default="running",
        index=True,
    )

    provider: Mapped[str] = mapped_column(String(50))
    model_name: Mapped[str] = mapped_column(String(160))
    prompt_version: Mapped[str] = mapped_column(String(40))

    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")

    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    elapsed_ms: Mapped[int] = mapped_column(Integer, default=0)

    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id"),
        nullable=True,
        index=True,
    )
    user_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
        index=True,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )


class AICitation(Base):
    """AI 输出与原始资料片段之间的引用关系。"""

    __tablename__ = "ai_citations"
    __table_args__ = (
        UniqueConstraint(
            "ai_run_id",
            "chunk_id",
            "citation_number",
            name="uq_ai_citation_position",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    ai_run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_runs.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id"),
        index=True,
    )

    citation_number: Mapped[int] = mapped_column(Integer)
    quote_text: Mapped[str] = mapped_column(Text, default="")
    relevance_score: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
    )


class KnowledgePointDraft(Base):
    """AI 抽取、尚未进入正式知识库的知识点。"""

    __tablename__ = "knowledge_point_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    ai_run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_runs.id"),
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id"),
        index=True,
    )

    name: Mapped[str] = mapped_column(String(160), index=True)
    category: Mapped[str] = mapped_column(String(30), default="概念")
    definition: Mapped[str] = mapped_column(Text, default="")
    formula: Mapped[str] = mapped_column(Text, default="")
    prerequisites_json: Mapped[str] = mapped_column(Text, default="[]")
    related_points_json: Mapped[str] = mapped_column(Text, default="[]")
    common_mistakes_json: Mapped[str] = mapped_column(Text, default="[]")
    importance: Mapped[int] = mapped_column(Integer, default=3)
    difficulty: Mapped[int] = mapped_column(Integer, default=3)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True,
    )
    review_note: Mapped[str] = mapped_column(Text, default="")
    accepted_knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )


class KnowledgePointDraftCitation(Base):
    """一条知识点草稿与其原始资料证据之间的关系。"""

    __tablename__ = "knowledge_point_draft_citations"
    __table_args__ = (
        UniqueConstraint(
            "draft_id",
            "chunk_id",
            name="uq_knowledge_draft_chunk",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_point_drafts.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id"),
        index=True,
    )
    quote_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class QuestionDraft(Base):
    """AI 生成、尚未进入正式题库的题目。"""

    __tablename__ = "question_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    ai_run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_runs.id"),
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id"),
        index=True,
    )
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id"),
        nullable=True,
        index=True,
    )

    kind: Mapped[str] = mapped_column(String(20))
    prompt: Mapped[str] = mapped_column(Text)
    answer: Mapped[str] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text, default="")
    options_json: Mapped[str] = mapped_column(Text, default="[]")
    tags_json: Mapped[str] = mapped_column(Text, default="[]")
    difficulty: Mapped[int] = mapped_column(Integer, default=3)

    status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        index=True,
    )
    review_note: Mapped[str] = mapped_column(Text, default="")
    accepted_question_id: Mapped[int | None] = mapped_column(
        ForeignKey("questions.id"),
        nullable=True,
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime,
        nullable=True,
    )



class QuestionDraftCitation(Base):
    """题目草稿与原始文档片段之间的引用关系。"""

    __tablename__ = "question_draft_citations"
    __table_args__ = (
        UniqueConstraint(
            "question_draft_id",
            "chunk_id",
            name="uq_question_draft_chunk",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)

    question_draft_id: Mapped[int] = mapped_column(
        ForeignKey("question_drafts.id", ondelete="CASCADE"),
        index=True,
    )

    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id"),
        index=True,
    )

    citation_number: Mapped[int] = mapped_column(Integer)
    quote_text: Mapped[str] = mapped_column(Text, default="")

    created_at: Mapped[datetime] = mapped_column(
        DateTime,
        default=datetime.now,
    )


class SubjectiveGradingResult(Base):
    """一次主观题 AI 批改结果；人工复核不会覆盖原始 AI 输出。"""

    __tablename__ = "subjective_grading_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    ai_run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_runs.id"), unique=True, index=True
    )
    attempt_id: Mapped[int] = mapped_column(
        ForeignKey("question_attempts.id"), index=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("questions.id"), index=True
    )
    total_score: Mapped[float] = mapped_column(Float)
    max_score: Mapped[float] = mapped_column(Float)
    rubric_json: Mapped[str] = mapped_column(Text, default="[]")
    strengths_json: Mapped[str] = mapped_column(Text, default="[]")
    missing_points_json: Mapped[str] = mapped_column(Text, default="[]")
    errors_json: Mapped[str] = mapped_column(Text, default="[]")
    feedback: Mapped[str] = mapped_column(Text, default="")
    improved_answer: Mapped[str] = mapped_column(Text, default="")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(
        String(20), default="completed", index=True
    )
    human_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    human_note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SubjectiveGradingCitation(Base):
    """主观题批改结果与原始文档片段之间的证据关系。"""

    __tablename__ = "subjective_grading_citations"
    __table_args__ = (
        UniqueConstraint(
            "grading_result_id",
            "chunk_id",
            name="uq_grading_result_chunk",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    grading_result_id: Mapped[int] = mapped_column(
        ForeignKey("subjective_grading_results.id", ondelete="CASCADE"),
        index=True,
    )
    chunk_id: Mapped[int] = mapped_column(
        ForeignKey("document_chunks.id"), index=True
    )
    citation_number: Mapped[int] = mapped_column(Integer)
    quote_text: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class ErrorAnalysisResult(Base):
    __tablename__ = "error_analysis_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    ai_run_id: Mapped[int] = mapped_column(ForeignKey("ai_runs.id"), index=True)
    attempt_id: Mapped[int] = mapped_column(ForeignKey("question_attempts.id"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("questions.id"), index=True)
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=True, index=True
    )
    error_types_json: Mapped[str] = mapped_column(Text, default="[]")
    severity: Mapped[str] = mapped_column(String(20), default="medium")
    explanation: Mapped[str] = mapped_column(Text, default="")
    missing_knowledge_json: Mapped[str] = mapped_column(Text, default="[]")
    recommended_exercises_json: Mapped[str] = mapped_column(Text, default="[]")
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    needs_human_review: Mapped[bool] = mapped_column(Boolean, default=True)
    human_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    human_note: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="needs_review", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LearningPlanDraft(Base):
    __tablename__ = "learning_plan_drafts"
    id: Mapped[int] = mapped_column(primary_key=True)
    ai_run_id: Mapped[int] = mapped_column(ForeignKey("ai_runs.id"), unique=True, index=True)
    goal_id: Mapped[int] = mapped_column(ForeignKey("study_goals.id"), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    risks_json: Mapped[str] = mapped_column(Text, default="[]")
    daily_minutes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class LearningPlanDraftTask(Base):
    __tablename__ = "learning_plan_draft_tasks"
    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(ForeignKey("learning_plan_drafts.id", ondelete="CASCADE"), index=True)
    position: Mapped[int] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(160))
    planned_date: Mapped[date] = mapped_column(Date)
    duration_minutes: Mapped[int] = mapped_column(Integer)
    priority: Mapped[str] = mapped_column(String(20))
    task_type: Mapped[str] = mapped_column(String(30))
    course_id: Mapped[int | None] = mapped_column(ForeignKey("courses.id"), nullable=True)
    knowledge_point_id: Mapped[int | None] = mapped_column(ForeignKey("knowledge_points.id"), nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")


class AdaptivePlanDraft(Base):
    """A deterministic next-week plan, kept separate until the learner confirms it."""

    __tablename__ = "adaptive_plan_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    report_snapshot_id: Mapped[int | None] = mapped_column(
        ForeignKey("learning_report_snapshots.id"), nullable=True, index=True
    )
    summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AdaptivePlanDraftTask(Base):
    __tablename__ = "adaptive_plan_draft_tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    draft_id: Mapped[int] = mapped_column(
        ForeignKey("adaptive_plan_drafts.id", ondelete="CASCADE"), index=True
    )
    position: Mapped[int] = mapped_column(Integer)
    planned_date: Mapped[date] = mapped_column(Date)
    title: Mapped[str] = mapped_column(String(160))
    duration_minutes: Mapped[int] = mapped_column(Integer)
    priority: Mapped[str] = mapped_column(String(20))
    layer: Mapped[str] = mapped_column(String(30))
    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id"), nullable=True
    )
    reason: Mapped[str] = mapped_column(Text, default="")


class LearningReportSnapshot(Base):
    """A generated learning report preserved with the data it was based on."""

    __tablename__ = "learning_report_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date] = mapped_column(Date, index=True)
    stats_json: Mapped[str] = mapped_column(Text, default="{}")
    report_markdown: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class ResearchRun(Base):
    """An auditable web-research request for one course."""

    __tablename__ = "research_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    query: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="completed", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class WebResourceCandidate(Base):
    """A web result and the model's relevance assessment before import."""

    __tablename__ = "web_resource_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    research_run_id: Mapped[int] = mapped_column(
        ForeignKey("research_runs.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(500), default="")
    url: Mapped[str] = mapped_column(String(2000), index=True)
    domain: Mapped[str] = mapped_column(String(255), default="", index=True)
    snippet: Mapped[str] = mapped_column(Text, default="")
    relevance_score: Mapped[int] = mapped_column(Integer, default=0, index=True)
    quality_score: Mapped[int] = mapped_column(Integer, default=0)
    decision_reason: Mapped[str] = mapped_column(Text, default="")
    learning_uses_json: Mapped[str] = mapped_column(Text, default="[]")
    # pending/rejected/imported/failed.  Import is only allowed from pending.
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    imported_resource_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_files.id"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentSession(Base):
    """A durable conversation in the unified AI center."""

    __tablename__ = "agent_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    title: Mapped[str] = mapped_column(String(160), default="New session")
    archived: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, index=True
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    role: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class AgentToolCall(Base):
    __tablename__ = "agent_tool_calls"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    tool_name: Mapped[str] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(20), index=True)
    detail: Mapped[str] = mapped_column(Text, default="")
    input_json: Mapped[str] = mapped_column(Text, default="{}")
    output_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AgentMemory(Base):
    """仅保存用户确认过的课程记忆和长期学习偏好。"""

    __tablename__ = "agent_memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    # course 是课程记忆，long_term 是跨课程偏好。
    scope: Mapped[str] = mapped_column(String(20), index=True)
    course_id: Mapped[int | None] = mapped_column(
        ForeignKey("courses.id"), nullable=True, index=True
    )
    # goal / plan_preference / weak_point / learning_pace
    category: Mapped[str] = mapped_column(String(40), index=True)
    content_json: Mapped[str] = mapped_column(Text, default="{}")
    source: Mapped[str] = mapped_column(String(30), default="user_confirmed")
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    deleted: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now
    )


class AgentHandoff(Base):
    """Records content delivered from an Agent conversation to an app module."""

    __tablename__ = "agent_handoffs"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    kind: Mapped[str] = mapped_column(String(50), index=True)
    target_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)


class AgentWorkflow(Base):
    """Durable state for the resource-to-report learning workflow."""

    __tablename__ = "agent_workflows"

    id: Mapped[int] = mapped_column(primary_key=True)
    tenant_id: Mapped[str | None] = mapped_column(String(36), index=True, nullable=True)
    session_id: Mapped[int] = mapped_column(
        ForeignKey("agent_sessions.id", ondelete="CASCADE"), index=True
    )
    course_id: Mapped[int] = mapped_column(ForeignKey("courses.id"), index=True)
    request: Mapped[str] = mapped_column(Text, default="")
    current_step: Mapped[str] = mapped_column(String(40), default="analyze", index=True)
    status: Mapped[str] = mapped_column(String(30), default="waiting_confirmation", index=True)
    context_json: Mapped[str] = mapped_column(Text, default="{}")
    error_message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, index=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now, onupdate=datetime.now, index=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
