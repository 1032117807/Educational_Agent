from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from app.database import Database
from app.models import (
    AIRun,
    ErrorAnalysisResult,
    KnowledgePoint,
    Question,
    QuestionAttempt,
    ReviewItem,
    SubjectiveGradingResult,
)


ERROR_TYPES = (
    "concept",
    "formula",
    "calculation",
    "reasoning",
    "question_reading",
    "expression",
    "knowledge_gap",
    "careless",
)


class ErrorAnalysisOutput(BaseModel):
    error_types: list[str] = Field(default_factory=list)
    severity: str
    explanation: str
    missing_knowledge: list[str] = Field(default_factory=list)
    recommended_exercises: list[str] = Field(default_factory=list)
    confidence: float = Field(ge=0, le=1)
    needs_human_review: bool


class StructuredErrorModel(Protocol):
    def invoke(self, input: object) -> ErrorAnalysisOutput:
        ...


@dataclass(frozen=True, slots=True)
class ErrorAnalysis:
    id: int
    attempt_id: int
    error_types: tuple[str, ...]
    severity: str
    explanation: str
    confidence: float
    needs_human_review: bool


PROMPT = ChatPromptTemplate.from_messages([
    ("system", """
你是学习错误分析助手。只能根据题目、学生答案、标准答案、主观题批改结果和知识点分析。
不要把空答案直接判断为概念错误。错误类型可以多选，只能使用：
concept, formula, calculation, reasoning, question_reading,
expression, knowledge_gap, careless。
如果证据不足、答案有多种合理解释或置信度低于 0.65，必须 needs_human_review=true。
""".strip()),
    ("human", """
题目：
{question}

学生答案：
{student_answer}

标准答案：
{reference_answer}

知识点：
{knowledge_point}

主观题批改结果：
{grading}

请输出结构化错误分析。
""".strip()),
])


class ErrorAnalysisService:
    def __init__(
        self,
        *,
        database: Database,
        chat_model: BaseChatModel | None = None,
        structured_model: StructuredErrorModel | None = None,
        provider: str,
        model_name: str,
    ) -> None:
        if chat_model is None and structured_model is None:
            raise ValueError("chat_model 和 structured_model 至少提供一个")
        self.database = database
        self.provider = provider
        self.model_name = model_name
        self.model = structured_model or chat_model.with_structured_output(
            ErrorAnalysisOutput
        )

    def analyze_attempt(self, attempt_id: int) -> ErrorAnalysis:
        with self.database.session() as session:
            attempt = session.get(QuestionAttempt, attempt_id)
            if attempt is None:
                raise ValueError("答题记录不存在")
            question = session.get(Question, attempt.question_id)
            if question is None:
                raise ValueError("题目不存在")
            knowledge = (
                session.get(KnowledgePoint, question.knowledge_point_id)
                if question.knowledge_point_id else None
            )
            grading = session.query(SubjectiveGradingResult).filter_by(
                attempt_id=attempt_id
            ).order_by(SubjectiveGradingResult.created_at.desc()).first()
            if not attempt.response.strip():
                raise ValueError("空答案不能进行错误原因分析")
            if attempt.correct is True:
                raise ValueError("正确答案不需要错误原因分析")

            run = AIRun(
                run_uuid=str(uuid4()),
                provider=self.provider,
                model_name=self.model_name,
                feature="error_analysis",
                prompt_version="error-analysis-v1",
                input_json=json.dumps({"attempt_id": attempt_id}, ensure_ascii=False),
                status="running",
            )
            session.add(run)
            session.flush()
            grading_data = {}
            if grading:
                grading_data = {
                    "feedback": grading.feedback,
                    "errors": json.loads(grading.errors_json or "[]"),
                    "missing_points": json.loads(grading.missing_points_json or "[]"),
                    "confidence": grading.confidence,
                }
            messages = PROMPT.invoke({
                "question": question.prompt,
                "student_answer": attempt.response,
                "reference_answer": question.answer,
                "knowledge_point": knowledge.name if knowledge else "",
                "grading": json.dumps(grading_data, ensure_ascii=False),
            })
            try:
                output = self.model.invoke(messages)
                self._validate(output, attempt.response)
                item = ErrorAnalysisResult(
                    ai_run_id=run.id,
                    attempt_id=attempt_id,
                    question_id=question.id,
                    knowledge_point_id=question.knowledge_point_id,
                    error_types_json=json.dumps(output.error_types, ensure_ascii=False),
                    severity=output.severity,
                    explanation=output.explanation,
                    missing_knowledge_json=json.dumps(
                        output.missing_knowledge, ensure_ascii=False
                    ),
                    recommended_exercises_json=json.dumps(
                        output.recommended_exercises, ensure_ascii=False
                    ),
                    confidence=output.confidence,
                    needs_human_review=output.needs_human_review,
                    human_confirmed=False,
                    status="needs_review",
                    created_at=datetime.now(),
                )
                session.add(item)
                session.flush()
                run.status = "completed"
                run.output_json = json.dumps(output.model_dump(), ensure_ascii=False)
                run.finished_at = datetime.now()
                return ErrorAnalysis(
                    id=item.id, attempt_id=attempt_id,
                    error_types=tuple(output.error_types),
                    severity=output.severity,
                    explanation=output.explanation,
                    confidence=output.confidence,
                    needs_human_review=output.needs_human_review,
                )
            except Exception as exc:
                run.status = "failed"
                run.error_message = str(exc)[:4000]
                run.finished_at = datetime.now()
                raise

    @staticmethod
    def _validate(output: ErrorAnalysisOutput, response: str) -> None:
        if not response.strip():
            raise ValueError("空答案不能标记为错误")
        unknown = set(output.error_types) - set(ERROR_TYPES)
        if unknown:
            raise ValueError(f"未知错误类型: {sorted(unknown)}")
        if not output.error_types:
            raise ValueError("至少需要一个错误类型")
        if output.severity not in {"low", "medium", "high"}:
            raise ValueError("severity 必须是 low、medium 或 high")
        if output.confidence < 0.65:
            output.needs_human_review = True

    def confirm(self, analysis_id: int, *, error_reason: str) -> None:
        with self.database.session() as session:
            item = session.get(ErrorAnalysisResult, analysis_id)
            if item is None:
                raise ValueError("错误分析不存在")
            attempt = session.get(QuestionAttempt, item.attempt_id)
            if attempt is None:
                raise ValueError("答题记录不存在")
            item.human_confirmed = True
            item.status = "confirmed"
            item.human_note = error_reason.strip()
            item.reviewed_at = datetime.now()
            review = session.query(ReviewItem).filter_by(
                question_id=item.question_id
            ).first()
            if review is None:
                review = ReviewItem(
                    question_id=item.question_id,
                    title="错误原因分析",
                    status="reviewing",
                )
                session.add(review)
            review.error_reason = error_reason.strip()[:300]
