from __future__ import annotations

import csv
import hashlib
import json
import random
import shutil
import sqlite3
import uuid
import zipfile
import tempfile
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any

from sqlalchemy import func, or_, select

from app.core.config import AppSettings
from app.database import Base, Database
from app.models import (
    AppSetting, BackgroundJob,
    Course,
    KnowledgePoint,
    PracticeSession, PracticeSessionQuestion,
    Question,
    QuestionAttempt,
    ResourceFile,
    ReviewAttempt,
    ReviewItem,
    StudySession,
    StudyTask,
    ToolCallLog,
)


class AnalyticsService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def summary(self, start: date, end: date, course_id: int | None = None) -> dict[str, Any]:
        start_dt = datetime.combine(start, datetime.min.time())
        end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time())
        with self.database.session() as session:
            study_stmt = select(StudySession).where(
                StudySession.started_at >= start_dt, StudySession.started_at < end_dt
            )
            task_stmt = select(StudyTask).where(
                StudyTask.planned_date >= start, StudyTask.planned_date <= end
            )
            practice_stmt = select(PracticeSession).where(
                PracticeSession.started_at >= start_dt, PracticeSession.started_at < end_dt,
                PracticeSession.status == "completed"
            )
            if course_id:
                study_stmt = study_stmt.where(StudySession.course_id == course_id)
                task_stmt = task_stmt.where(StudyTask.course_id == course_id)
                practice_stmt = practice_stmt.where(PracticeSession.course_id == course_id)
            study = list(session.scalars(study_stmt))
            tasks = list(session.scalars(task_stmt))
            practices = list(session.scalars(practice_stmt))
            reviews = list(session.scalars(select(ReviewAttempt).where(
                ReviewAttempt.created_at >= start_dt, ReviewAttempt.created_at < end_dt
            )))
            attempts = list(session.scalars(select(QuestionAttempt).where(
                QuestionAttempt.attempted_at >= start_dt, QuestionAttempt.attempted_at < end_dt
            )))
            total_questions = sum(item.total for item in practices)
            total_correct = sum(item.correct for item in practices)
            daily = {start + timedelta(days=i): 0 for i in range((end - start).days + 1)}
            for item in study:
                daily[item.started_at.date()] = daily.get(item.started_at.date(), 0) + item.duration_minutes
            course_names = {item.id: item.name for item in session.scalars(select(Course))}
            course_minutes: dict[str, int] = {}
            for item in study:
                name = course_names.get(item.course_id, "未关联")
                course_minutes[name] = course_minutes.get(name, 0) + item.duration_minutes
            weekly_tasks: dict[str, tuple[int, int]] = {}
            for item in tasks:
                key = f"{item.planned_date.isocalendar().year}-W{item.planned_date.isocalendar().week:02d}"
                total, done = weekly_tasks.get(key, (0, 0))
                weekly_tasks[key] = (total + 1, done + int(item.completed))
            knowledge_stmt = select(KnowledgePoint).order_by(KnowledgePoint.mastery)
            if course_id:
                knowledge_stmt = knowledge_stmt.where(KnowledgePoint.course_id == course_id)
            knowledge = list(session.scalars(knowledge_stmt))
            error_types: dict[str, int] = {}
            accuracy_daily: dict[date, tuple[int, int]] = {}
            for attempt in attempts:
                question = session.get(Question, attempt.question_id)
                if course_id and (not question or question.course_id != course_id):
                    continue
                if attempt.correct is False and question:
                    error_types[question.kind] = error_types.get(question.kind, 0) + 1
                if attempt.correct is not None:
                    day = attempt.attempted_at.date()
                    total, correct = accuracy_daily.get(day, (0, 0))
                    accuracy_daily[day] = (total + 1, correct + int(attempt.correct))
            return {
                "study_minutes": sum(item.duration_minutes for item in study),
                "tasks_total": len(tasks),
                "tasks_done": sum(1 for item in tasks if item.completed),
                "practice_questions": total_questions,
                "accuracy": round(total_correct * 100 / total_questions, 1) if total_questions else 0.0,
                "reviews": len(reviews),
                "daily": daily,
                "course_minutes": course_minutes,
                "weekly_tasks": weekly_tasks,
                "knowledge": [{"name": item.name, "mastery": item.mastery} for item in knowledge],
                "error_types": error_types,
                "accuracy_daily": {
                    day: round(correct * 100 / total, 1)
                    for day, (total, correct) in accuracy_daily.items()
                },
            }

    def list_courses(self) -> list[Course]:
        with self.database.session() as session:
            return list(session.scalars(select(Course).where(Course.status == "active").order_by(Course.name)))

    def export_csv(self, path: Path, start: date, end: date, course_id: int | None = None) -> None:
        data = self.summary(start, end, course_id)
        with path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            writer.writerow(["日期", "学习分钟"])
            for day, minutes in data["daily"].items():
                writer.writerow([day.isoformat(), minutes])


