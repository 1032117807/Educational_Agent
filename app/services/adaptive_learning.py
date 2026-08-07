from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.database import Database
from app.models import (
    AdaptivePlanDraft, AdaptivePlanDraftTask, KnowledgePoint, PracticeSession,
    Question, QuestionAttempt, ReviewItem, StudyTask,
)
from app.services.assessment import QuestionService


@dataclass(frozen=True)
class AdaptiveRecommendation:
    knowledge_point_id: int
    name: str
    mastery: int
    accuracy: float | None
    wrong_count: int
    overdue_days: int
    error_reasons: tuple[str, ...]
    layer: str
    priority: int


@dataclass(frozen=True)
class AdaptivePlanDraftView:
    id: int
    summary: str
    status: str
    tasks: tuple[dict[str, object], ...]


class AdaptiveLearningService:
    """Turns durable practice evidence into review queues and confirmable plans."""

    LAYERS = {"foundation", "error_focus", "application"}

    def __init__(self, database: Database) -> None:
        self.database = database
        self.questions = QuestionService(database)

    def recommendations(self, course_id: int, *, limit: int = 12) -> list[AdaptiveRecommendation]:
        today = date.today()
        with self.database.session() as session:
            points = list(session.scalars(select(KnowledgePoint).where(
                KnowledgePoint.course_id == course_id
            )))
            questions = list(session.scalars(select(Question).where(
                Question.course_id == course_id, ~Question.archived
            )))
            attempts = list(session.scalars(select(QuestionAttempt).join(
                PracticeSession, PracticeSession.id == QuestionAttempt.session_id
            ).where(PracticeSession.course_id == course_id)))
            reviews = list(session.scalars(select(ReviewItem).join(
                Question, Question.id == ReviewItem.question_id
            ).where(Question.course_id == course_id, ReviewItem.status != "archived")))

        question_points = {item.id: item.knowledge_point_id for item in questions}
        stats: dict[int, dict[str, object]] = {
            point.id: {"judged": 0, "correct": 0, "wrong": 0, "reasons": set()}
            for point in points
        }
        for attempt in attempts:
            point_id = question_points.get(attempt.question_id)
            if point_id not in stats or attempt.correct is None:
                continue
            item = stats[point_id]
            item["judged"] = int(item["judged"]) + 1
            if attempt.correct:
                item["correct"] = int(item["correct"]) + 1
            else:
                item["wrong"] = int(item["wrong"]) + 1

        overdue: dict[int, int] = {}
        for review in reviews:
            point_id = question_points.get(review.question_id)
            if point_id not in stats:
                continue
            stats[point_id]["wrong"] = int(stats[point_id]["wrong"]) + review.wrong_count
            if review.error_reason.strip():
                stats[point_id]["reasons"].add(review.error_reason.strip())
            overdue[point_id] = max(overdue.get(point_id, 0), max(0, (today - review.next_review).days))

        rows: list[AdaptiveRecommendation] = []
        for point in points:
            item = stats[point.id]
            judged, correct, wrong = int(item["judged"]), int(item["correct"]), int(item["wrong"])
            accuracy = correct / judged if judged else None
            if point.mastery < 45:
                layer = "foundation"
            elif wrong or (accuracy is not None and accuracy < 0.7):
                layer = "error_focus"
            else:
                layer = "application"
            score = (100 - point.mastery) * 0.5 + wrong * 12 + overdue.get(point.id, 0) * 2
            if accuracy is not None:
                score += (1 - accuracy) * 30
            rows.append(AdaptiveRecommendation(
                point.id, point.name, point.mastery, accuracy, wrong, overdue.get(point.id, 0),
                tuple(sorted(item["reasons"])), layer, round(score),
            ))
        return sorted(rows, key=lambda item: (-item.priority, item.mastery, item.name))[:limit]

    def create_layered_practice(self, course_id: int, layer: str, *, count: int = 8):
        if layer not in self.LAYERS:
            raise ValueError("Unknown adaptive practice layer")
        recommendations = self.recommendations(course_id)
        point_ids = [item.knowledge_point_id for item in recommendations if item.layer == layer]
        if not point_ids:
            raise ValueError("No knowledge points currently need this practice layer")
        with self.database.session() as session:
            questions = list(session.scalars(select(Question).where(
                Question.course_id == course_id, Question.knowledge_point_id.in_(point_ids), ~Question.archived
            )))
            attempts = list(session.scalars(select(QuestionAttempt).where(
                QuestionAttempt.question_id.in_([item.id for item in questions])
            ))) if questions else []
        wrong_ids = {item.question_id for item in attempts if item.correct is False}
        attempted_ids = {item.question_id for item in attempts}
        if layer == "foundation":
            questions.sort(key=lambda item: (item.difficulty, item.id))
        elif layer == "error_focus":
            questions.sort(key=lambda item: (item.id not in wrong_ids, item.difficulty, item.id))
        else:
            questions.sort(key=lambda item: (item.id in attempted_ids, -item.difficulty, item.id))
        return self.questions.create_practice_for_questions([item.id for item in questions[:max(1, count)]])

    def create_error_transfer_practice(self, question_id: int, *, count: int = 6):
        """Use existing same-point questions as variations, then linked points as transfer."""
        with self.database.session() as session:
            source = session.get(Question, question_id)
            if source is None or source.knowledge_point_id is None:
                raise ValueError("The wrong question is not linked to a knowledge point")
            point = session.get(KnowledgePoint, source.knowledge_point_id)
            related_ids = []
            if point is not None:
                try:
                    related_ids = [int(value) for value in json.loads(point.related_points_json or "[]")]
                except (TypeError, ValueError, json.JSONDecodeError):
                    related_ids = []
            variants = list(session.scalars(select(Question).where(
                Question.course_id == source.course_id, ~Question.archived,
                Question.knowledge_point_id == source.knowledge_point_id,
                Question.id != source.id,
            ).order_by(Question.difficulty, Question.id)))
            transfers = list(session.scalars(select(Question).where(
                Question.course_id == source.course_id, ~Question.archived,
                Question.knowledge_point_id.in_(related_ids),
            ).order_by(Question.difficulty.desc(), Question.id))) if related_ids else []
        selected = [item.id for item in variants + transfers][:max(1, count)]
        if not selected:
            raise ValueError("Add same-point or related-point questions before creating a variation practice")
        return self.questions.create_practice_for_questions(selected)

    def create_next_week_draft(self, course_id: int, *, report_snapshot_id: int | None = None) -> AdaptivePlanDraftView:
        recommendations = self.recommendations(course_id, limit=6)
        if not recommendations:
            raise ValueError("Add knowledge points and practice records before creating an adaptive plan")
        monday = date.today() + timedelta(days=(7 - date.today().weekday()))
        tasks = []
        for position, recommendation in enumerate(recommendations):
            day = monday + timedelta(days=position % 7)
            label = {"foundation": "基础巩固", "error_focus": "易错强化", "application": "综合应用"}[recommendation.layer]
            tasks.append({
                "planned_date": day, "title": f"{label}：{recommendation.name}",
                "duration_minutes": 35 if recommendation.layer != "application" else 45,
                "priority": "高" if recommendation.priority >= 55 else "中",
                "layer": recommendation.layer, "knowledge_point_id": recommendation.knowledge_point_id,
                "reason": f"掌握度 {recommendation.mastery}%；错题 {recommendation.wrong_count}；逾期 {recommendation.overdue_days} 天",
            })
        summary = "根据掌握度、答题正确率、错题与遗忘间隔生成；确认前不会创建学习任务。"
        with self.database.session() as session:
            draft = AdaptivePlanDraft(course_id=course_id, report_snapshot_id=report_snapshot_id, summary=summary)
            session.add(draft)
            session.flush()
            for position, task in enumerate(tasks):
                session.add(AdaptivePlanDraftTask(draft_id=draft.id, position=position, **task))
            session.flush()
            return self._view(session, draft)

    def get_draft(self, draft_id: int) -> AdaptivePlanDraftView:
        with self.database.session() as session:
            draft = session.get(AdaptivePlanDraft, draft_id)
            if draft is None:
                raise ValueError("Adaptive plan draft does not exist")
            return self._view(session, draft)

    def confirm_draft(self, draft_id: int) -> int:
        with self.database.session() as session:
            draft = session.get(AdaptivePlanDraft, draft_id)
            if draft is None:
                raise ValueError("Adaptive plan draft does not exist")
            if draft.status == "confirmed":
                return 0
            if draft.status != "pending":
                raise ValueError("Adaptive plan draft cannot be confirmed")
            rows = list(session.scalars(select(AdaptivePlanDraftTask).where(
                AdaptivePlanDraftTask.draft_id == draft.id
            ).order_by(AdaptivePlanDraftTask.position)))
            for row in rows:
                session.add(StudyTask(
                    title=row.title, course_id=draft.course_id, task_type="adaptive_review",
                    planned_date=row.planned_date, duration_minutes=row.duration_minutes,
                    priority=row.priority, note=row.reason, source="adaptive_plan",
                ))
            draft.status = "confirmed"
            draft.confirmed_at = datetime.now()
            return len(rows)

    @staticmethod
    def _view(session, draft: AdaptivePlanDraft) -> AdaptivePlanDraftView:
        rows = list(session.scalars(select(AdaptivePlanDraftTask).where(
            AdaptivePlanDraftTask.draft_id == draft.id
        ).order_by(AdaptivePlanDraftTask.position)))
        return AdaptivePlanDraftView(draft.id, draft.summary, draft.status, tuple({
            "date": row.planned_date, "title": row.title, "duration_minutes": row.duration_minutes,
            "priority": row.priority, "layer": row.layer, "reason": row.reason,
        } for row in rows))
