from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
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
    ai_run_id: Mapped[int] = mapped_column(
        ForeignKey("ai_runs.id"),
        index=True,
    )
    course_id: Mapped[int] = mapped_column(
        ForeignKey("courses.id"),
        index=True,
    )

    name: Mapped[str] = mapped_column(String(160), index=True)
    definition: Mapped[str] = mapped_column(Text, default="")
    formula: Mapped[str] = mapped_column(Text, default="")
    prerequisites_json: Mapped[str] = mapped_column(Text, default="[]")
    related_points_json: Mapped[str] = mapped_column(Text, default="[]")
    common_mistakes_json: Mapped[str] = mapped_column(Text, default="[]")
    importance: Mapped[int] = mapped_column(Integer, default=3)

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


class QuestionDraft(Base):
    """AI 生成、尚未进入正式题库的题目。"""

    __tablename__ = "question_drafts"

    id: Mapped[int] = mapped_column(primary_key=True)
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