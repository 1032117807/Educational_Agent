from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import Database
from app.models import QuestionAttempt, StudySession, StudyTask, KnowledgePoint


@dataclass(frozen=True)
class LearningStats:
    start_date: date
    end_date: date
    study_minutes: int
    task_total: int
    task_completed: int
    task_completion_rate: float
    attempt_total: int
    correct_total: int
    accuracy: float
    weak_points: tuple[dict, ...]
    error_types: dict[str, int]


class ReportExplanation(BaseModel):
    summary: str
    strengths: list[str] = Field(default_factory=list)
    weaknesses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    next_week_priorities: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class LearningReport:
    stats: LearningStats
    explanation: ReportExplanation


PROMPT = ChatPromptTemplate.from_messages([
    ("system", """
你是学习分析助手。输入数据已经由程序计算完成，不能修改任何数字。
你只能解释数据、指出趋势并提出建议；数据不足时必须明确说明。
""".strip()),
    ("human", "请根据以下真实统计数据生成学习报告：\n{stats}"),
])


class LearningReportService:
    def __init__(self, *, database: Database, chat_model: BaseChatModel) -> None:
        self.database = database
        self.model = chat_model.with_structured_output(ReportExplanation)

    def calculate_stats(self, *, start_date: date, end_date: date) -> LearningStats:
        if end_date < start_date:
            raise ValueError("结束日期不能早于开始日期")
        begin = datetime.combine(start_date, datetime.min.time())
        finish = datetime.combine(end_date + timedelta(days=1), datetime.min.time())
        with self.database.session() as session:
            sessions = list(session.scalars(select(StudySession).where(
                StudySession.started_at >= begin,
                StudySession.started_at < finish,
            )))
            tasks = list(session.scalars(select(StudyTask).where(
                StudyTask.planned_date >= start_date,
                StudyTask.planned_date <= end_date,
            )))
            attempts = list(session.scalars(select(QuestionAttempt).where(
                QuestionAttempt.attempted_at >= begin,
                QuestionAttempt.attempted_at < finish,
            )))
            points = list(session.scalars(
                select(KnowledgePoint).order_by(KnowledgePoint.mastery.asc()).limit(10)
            ))

        judged = [item for item in attempts if item.correct is not None]
        completed = sum(1 for item in tasks if item.completed)
        correct = sum(1 for item in judged if item.correct is True)
        errors = {"wrong_answer": sum(1 for item in judged if item.correct is False)}
        return LearningStats(
            start_date=start_date,
            end_date=end_date,
            study_minutes=sum(max(0, item.duration_minutes) for item in sessions),
            task_total=len(tasks),
            task_completed=completed,
            task_completion_rate=completed / len(tasks) if tasks else 0.0,
            attempt_total=len(judged),
            correct_total=correct,
            accuracy=correct / len(judged) if judged else 0.0,
            weak_points=tuple({"id": p.id, "name": p.name, "mastery": p.mastery} for p in points),
            error_types=errors,
        )

    def generate(self, *, start_date: date, end_date: date) -> LearningReport:
        stats = self.calculate_stats(start_date=start_date, end_date=end_date)
        explanation = self.model.invoke(PROMPT.invoke({
            "stats": json.dumps(asdict(stats), ensure_ascii=False, default=str),
        }))
        return LearningReport(stats=stats, explanation=explanation)
