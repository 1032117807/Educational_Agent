"""Build a minimal, read-only learning-data snapshot for temporary code."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.database import Database
from app.models import KnowledgePoint, PracticeSession, Question, QuestionAttempt, StudySession, StudyTask


class LearningSnapshotService:
    """Exports aggregate-safe records, never database handles or source files."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def build(self, *, days: int = 30, course_id: int | None = None) -> dict:
        days = max(1, min(int(days), 90))
        start_date = date.today() - timedelta(days=days - 1)
        start = datetime.combine(start_date, datetime.min.time())
        with self.database.session() as session:
            study_query = select(StudySession).where(StudySession.started_at >= start)
            task_query = select(StudyTask).where(StudyTask.planned_date >= start_date)
            point_query = select(KnowledgePoint)
            if course_id is not None:
                study_query = study_query.where(StudySession.course_id == course_id)
                task_query = task_query.where(StudyTask.course_id == course_id)
                point_query = point_query.where(KnowledgePoint.course_id == course_id)
            studies = list(session.scalars(study_query.order_by(StudySession.started_at).limit(500)))
            tasks = list(session.scalars(task_query.order_by(StudyTask.planned_date).limit(300)))
            points = list(session.scalars(point_query.order_by(KnowledgePoint.mastery).limit(100)))

            attempt_query = (
                select(QuestionAttempt, Question, PracticeSession)
                .join(Question, Question.id == QuestionAttempt.question_id)
                .join(PracticeSession, PracticeSession.id == QuestionAttempt.session_id)
                .where(QuestionAttempt.attempted_at >= start)
            )
            if course_id is not None:
                attempt_query = attempt_query.where(PracticeSession.course_id == course_id)
            attempts = list(session.execute(
                attempt_query.order_by(QuestionAttempt.attempted_at).limit(800)
            ).all())

        return {
            "scope": "read_only_learning_snapshot",
            "days": days,
            "start_date": start_date.isoformat(),
            "end_date": date.today().isoformat(),
            "course_id": course_id,
            "study_sessions": [{
                "date": item.started_at.date().isoformat(),
                "duration_minutes": max(0, item.duration_minutes),
                "course_id": item.course_id,
            } for item in studies],
            "tasks": [{
                "date": item.planned_date.isoformat(),
                "duration_minutes": max(0, item.duration_minutes),
                "completed": item.completed,
                "course_id": item.course_id,
            } for item in tasks],
            "attempts": [{
                "date": attempt.attempted_at.date().isoformat(),
                "correct": attempt.correct,
                "elapsed_seconds": max(0, attempt.elapsed_seconds),
                "knowledge_point_id": question.knowledge_point_id,
                "difficulty": question.difficulty,
            } for attempt, question, _practice in attempts],
            "knowledge_points": [{
                "id": item.id,
                "name": item.name,
                "mastery": item.mastery,
                "difficulty": item.difficulty,
                "importance": item.importance,
            } for item in points],
        }
