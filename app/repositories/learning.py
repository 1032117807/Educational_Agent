from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.models import Course, Question, ReviewItem, StudyGoal, StudyTask


class CourseRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(
        self, search: str = "", status: str = "active",
        stage: str = "", subject: str = ""
    ) -> list[Course]:
        stmt = select(Course).where(Course.status == status)
        if search:
            term = f"%{search}%"
            stmt = stmt.where(or_(Course.name.ilike(term), Course.subject.ilike(term)))
        if stage:
            stmt = stmt.where(Course.education_stage == stage)
        if subject:
            stmt = stmt.where(Course.subject == subject)
        return list(self.session.scalars(stmt.order_by(Course.updated_at.desc())))

    def add(self, **values: object) -> Course:
        item = Course(**values)
        self.session.add(item)
        self.session.flush()
        return item

    def archive(self, course_id: int) -> None:
        course = self.session.get(Course, course_id)
        if course:
            course.status = "archived"

    def get(self, course_id: int) -> Course | None:
        return self.session.get(Course, course_id)


class TaskRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_for_day(self, day: date) -> list[StudyTask]:
        return list(self.session.scalars(
            select(StudyTask).where(StudyTask.planned_date == day).order_by(StudyTask.completed, StudyTask.id)
        ))

    def list_range(self, start: date, end: date) -> list[StudyTask]:
        return list(self.session.scalars(
            select(StudyTask).where(
                StudyTask.planned_date >= start, StudyTask.planned_date <= end
            ).order_by(StudyTask.planned_date, StudyTask.scheduled_time, StudyTask.id)
        ))

    def add(self, **values: object) -> StudyTask:
        item = StudyTask(**values)
        self.session.add(item)
        self.session.flush()
        return item

    def complete(self, task_id: int) -> None:
        item = self.session.get(StudyTask, task_id)
        if item:
            item.completed = True
            item.completed_at = datetime.now()

    def get(self, task_id: int) -> StudyTask | None:
        return self.session.get(StudyTask, task_id)

    def delete(self, task_id: int) -> None:
        item = self.get(task_id)
        if item:
            self.session.delete(item)


class GoalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list(self) -> list[StudyGoal]:
        return list(self.session.scalars(
            select(StudyGoal).where(StudyGoal.status == "active").order_by(StudyGoal.target_date)
        ))

    def add(self, **values: object) -> StudyGoal:
        item = StudyGoal(**values)
        self.session.add(item)
        self.session.flush()
        return item

    def get(self, goal_id: int) -> StudyGoal | None:
        return self.session.get(StudyGoal, goal_id)

    def archive(self, goal_id: int) -> None:
        item = self.get(goal_id)
        if item:
            item.status = "archived"


class StatsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def counts(self) -> dict[str, int]:
        today = date.today()
        return {
            "today": self.session.scalar(select(func.count()).select_from(StudyTask).where(StudyTask.planned_date == today)) or 0,
            "done": self.session.scalar(select(func.count()).select_from(StudyTask).where(StudyTask.planned_date == today, StudyTask.completed)) or 0,
            "due": self.session.scalar(select(func.count()).select_from(ReviewItem).where(ReviewItem.next_review <= today, ReviewItem.status != "mastered")) or 0,
            "courses": self.session.scalar(select(func.count()).select_from(Course).where(Course.status == "active")) or 0,
            "questions": self.session.scalar(select(func.count()).select_from(Question).where(~Question.archived)) or 0,
        }
