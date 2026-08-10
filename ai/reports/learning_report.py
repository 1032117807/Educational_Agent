from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.database import Database
from app.models import (
    KnowledgePoint,
    LearningReportSnapshot,
    QuestionAttempt,
    StudySession,
    StudyTask,
)
from app.services.report_visualization import ReportVisualizationService


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
    task_evidence: tuple[dict, ...] = ()
    practice_evidence: tuple[dict, ...] = ()
    progress_formula: str = "knowledge 45% + tasks 20% + accuracy 25% + consistency 10%"


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
    chart_paths: tuple[str, ...] = ()


@dataclass(frozen=True)
class SavedLearningReport:
    id: int
    start_date: date
    end_date: date
    markdown: str
    created_at: datetime


def render_learning_report(report: LearningReport) -> str:
    stats = report.stats
    explanation = report.explanation

    def format_list(items: list[str]) -> str:
        return "\n".join(f"- {item}" for item in items) if items else "- 暂无"

    chart_section = []
    if report.chart_paths:
        chart_section = ["", "## 数据图表"]
        chart_section.extend(
            f"![学习数据图表 {index}](file:///{path.replace(chr(92), '/')})"
            for index, path in enumerate(report.chart_paths, 1)
        )
    return ("\n".join([
        "# AI 学习报告",
        f"周期：{stats.start_date} 至 {stats.end_date}",
        "",
        "## 真实统计",
        f"- 学习时长：{stats.study_minutes} 分钟",
        f"- 任务完成：{stats.task_completed}/{stats.task_total}（{stats.task_completion_rate:.0%}）",
        f"- 练习正确：{stats.correct_total}/{stats.attempt_total}（{stats.accuracy:.0%}）",
        "",
        "## 总结",
        explanation.summary,
        "",
        "## 优势",
        format_list(explanation.strengths),
        "",
        "## 薄弱点",
        format_list(explanation.weaknesses),
        "",
        "## 建议",
        format_list(explanation.recommendations),
        "",
        "## 下周重点",
        format_list(explanation.next_week_priorities),
        *chart_section,
    ]) + "\n\n## Data basis\n"
        f"- Objective progress formula: {stats.progress_formula}\n"
        "- Knowledge points used:\n"
        + format_list([f"{item['name']} ({item['mastery']}%)" for item in stats.weak_points])
        + "\n- Tasks counted:\n"
        + format_list([f"{item['title']} ({item['status']})" for item in stats.task_evidence])
        + "\n- Practice attempts counted:\n"
        + format_list([f"question {item['question_id']}: {item['result']}" for item in stats.practice_evidence]))


PROMPT = ChatPromptTemplate.from_messages([
    ("system", """
你是学习分析助手。输入数据已经由程序计算完成，不能修改任何数字。
你只能解释数据、指出趋势并提出建议；数据不足时必须明确说明。
""".strip()),
    ("human", "请根据以下真实统计数据生成学习报告：\n{stats}"),
])


class LearningReportService:
    def __init__(
        self, *, database: Database, chat_model: BaseChatModel,
        visualization_service: ReportVisualizationService | None = None,
    ) -> None:
        self.database = database
        self.model = chat_model.with_structured_output(ReportExplanation)
        self.visualization_service = visualization_service

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
            task_evidence=tuple({
                "title": item.title,
                "status": "completed" if item.completed else "incomplete",
                "date": item.planned_date.isoformat(),
            } for item in tasks),
            practice_evidence=tuple({
                "question_id": item.question_id,
                "result": "correct" if item.correct else "incorrect",
            } for item in judged),
        )

    def generate(self, *, start_date: date, end_date: date) -> LearningReport:
        stats = self.calculate_stats(start_date=start_date, end_date=end_date)
        explanation = self.model.invoke(PROMPT.invoke({
            "stats": json.dumps(asdict(stats), ensure_ascii=False, default=str),
        }))
        chart_paths = (
            tuple(str(path) for path in self.visualization_service.render(stats))
            if self.visualization_service is not None else ()
        )
        return LearningReport(stats=stats, explanation=explanation, chart_paths=chart_paths)

    def save_snapshot(self, report: LearningReport, markdown: str) -> SavedLearningReport:
        with self.database.session() as session:
            snapshot = LearningReportSnapshot(
                start_date=report.stats.start_date,
                end_date=report.stats.end_date,
                stats_json=json.dumps(asdict(report.stats), ensure_ascii=False, default=str),
                report_markdown=markdown,
            )
            session.add(snapshot)
            session.flush()
            return SavedLearningReport(
                id=snapshot.id,
                start_date=snapshot.start_date,
                end_date=snapshot.end_date,
                markdown=snapshot.report_markdown,
                created_at=snapshot.created_at,
            )

    def list_snapshots(self, *, limit: int = 50) -> list[SavedLearningReport]:
        with self.database.session() as session:
            snapshots = list(session.scalars(
                select(LearningReportSnapshot)
                .order_by(LearningReportSnapshot.created_at.desc())
                .limit(limit)
            ))
        return [
            SavedLearningReport(
                id=item.id,
                start_date=item.start_date,
                end_date=item.end_date,
                markdown=item.report_markdown,
                created_at=item.created_at,
            )
            for item in snapshots
        ]
