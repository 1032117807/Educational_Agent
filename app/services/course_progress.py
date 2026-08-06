from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.database import Database
from app.models import Course, KnowledgePoint, Question, QuestionAttempt, StudySession, StudyTask


class CourseProgressService:
    """Computes course progress only from recorded learning evidence."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def calculate(self, course_id: int) -> dict[str, object]:
        today = date.today()
        begin = datetime.combine(today - timedelta(days=6), datetime.min.time())
        with self.database.session() as session:
            course = session.get(Course, course_id)
            if course is None:
                raise ValueError("Course does not exist")
            points = list(session.scalars(
                select(KnowledgePoint).where(KnowledgePoint.course_id == course_id)
            ))
            tasks = list(session.scalars(
                select(StudyTask).where(
                    StudyTask.course_id == course_id,
                    StudyTask.planned_date <= today,
                )
            ))
            sessions = list(session.scalars(
                select(StudySession).where(
                    StudySession.course_id == course_id,
                    StudySession.started_at >= begin,
                )
            ))
            attempts = list(session.scalars(
                select(QuestionAttempt).where(QuestionAttempt.attempted_at >= begin)
            ))
            question_ids = {
                item.id for item in session.scalars(
                    select(Question).where(Question.course_id == course_id)
                )
            }
            attempts = [item for item in attempts if item.question_id in question_ids]

            knowledge_score = sum(item.mastery for item in points) / len(points) if points else 0.0
            task_score = (
                sum(1 for item in tasks if item.completed) * 100 / len(tasks)
                if tasks else 0.0
            )
            judged = [item for item in attempts if item.correct is not None]
            accuracy_score = (
                sum(1 for item in judged if item.correct) * 100 / len(judged)
                if judged else 0.0
            )
            study_days = {item.started_at.date() for item in sessions if item.duration_minutes > 0}
            consistency_score = len(study_days) * 100 / 7
            progress = round(
                knowledge_score * 0.45
                + task_score * 0.20
                + accuracy_score * 0.25
                + consistency_score * 0.10
            )
            return {
                "course_id": course_id,
                "progress": max(0, min(100, progress)),
                "knowledge_score": round(knowledge_score, 1),
                "task_score": round(task_score, 1),
                "accuracy_score": round(accuracy_score, 1),
                "consistency_score": round(consistency_score, 1),
                "evidence": {
                    "knowledge_points": len(points),
                    "due_tasks": len(tasks),
                    "judged_attempts": len(judged),
                    "study_days_last_7": len(study_days),
                    "study_minutes_last_7": sum(max(0, item.duration_minutes) for item in sessions),
                },
            }

    def refresh(self, course_id: int) -> dict[str, object]:
        result = self.calculate(course_id)
        with self.database.session() as session:
            course = session.get(Course, course_id)
            if course is not None:
                course.progress = int(result["progress"])
        return result

    def refresh_all(self) -> list[dict[str, object]]:
        with self.database.session() as session:
            course_ids = list(session.scalars(select(Course.id).where(Course.status == "active")))
        return [self.refresh(course_id) for course_id in course_ids]

    def recommended_daily_minutes(
        self, course_id: int, *, weekly_minutes: int, remaining_days: int
    ) -> dict[str, object]:
        evidence = self.calculate(course_id)
        actual = float(evidence["evidence"]["study_minutes_last_7"]) / 7
        baseline = max(20.0, weekly_minutes / 7)
        load = max(baseline, actual)
        if float(evidence["knowledge_score"]) < 50:
            load *= 1.15
        if float(evidence["task_score"]) < 60:
            load *= 1.10
        if remaining_days <= 14:
            load *= 1.15
        minutes = round(max(20, min(240, load)))
        return {
            "daily_minutes": minutes,
            "baseline_minutes": round(baseline),
            "actual_average_minutes": round(actual),
            "reason": "based on recent study time, mastery, task completion, and deadline",
            "progress": evidence["progress"],
        }
