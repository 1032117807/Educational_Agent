from __future__ import annotations

from datetime import date, datetime, timedelta

from sqlalchemy import select

from app.database import Database
from app.repositories.learning import CourseRepository, GoalRepository, StatsRepository, TaskRepository
from app.models import Course, KnowledgePoint, StudySession, StudyTask
from app.services.course_progress import CourseProgressService


class LearningService:
    def __init__(self, database: Database) -> None:
        self.database = database

    def dashboard(self) -> dict[str, object]:
        with self.database.session() as session:
            stats = StatsRepository(session).counts()
            monday = date.today() - timedelta(days=date.today().weekday())
            study_sessions = list(session.scalars(
                select(StudySession).where(StudySession.started_at >= datetime.combine(monday, datetime.min.time()))
            ))
            stats["week_minutes"] = sum(item.duration_minutes for item in study_sessions)
            all_days = {
                item.started_at.date() for item in session.scalars(select(StudySession))
                if item.duration_minutes > 0
            }
            streak = 0
            cursor = date.today()
            while cursor in all_days:
                streak += 1
                cursor -= timedelta(days=1)
            stats["streak"] = streak
            tasks = TaskRepository(session).list_for_day(date.today())
            courses = CourseRepository(session).list()
            weak = list(session.scalars(
                select(KnowledgePoint).order_by(KnowledgePoint.mastery).limit(8)
            ))
            daily = {date.today() - timedelta(days=offset): 0 for offset in range(6, -1, -1)}
            week_start = datetime.combine(date.today() - timedelta(days=6), datetime.min.time())
            for item in session.scalars(select(StudySession).where(StudySession.started_at >= week_start)):
                daily[item.started_at.date()] = daily.get(item.started_at.date(), 0) + item.duration_minutes
            return {
                "stats": stats, "tasks": tasks, "courses": courses[:4],
                "weak": weak, "daily": daily,
            }

    def list_courses(
        self, search: str = "", status: str = "active",
        stage: str = "", subject: str = ""
    ) -> list[object]:
        with self.database.session() as session:
            return CourseRepository(session).list(search, status, stage, subject)

    def create_course(
        self, name: str, stage: str, subject: str, description: str = "",
        grade_level: str = "", exam_type: str = "", textbook_version: str = "",
        target_date: date | None = None, target_score: float | None = None, progress: int = 0
    ) -> object:
        if not name.strip():
            raise ValueError("课程名称不能为空")
        with self.database.session() as session:
            return CourseRepository(session).add(
                name=name.strip(), education_stage=stage, subject=subject, description=description.strip(),
                grade_level=grade_level.strip(), exam_type=exam_type.strip(),
                textbook_version=textbook_version.strip(), target_date=target_date,
                target_score=target_score, progress=max(0, min(100, progress))
            )

    def get_course(self, course_id: int) -> object | None:
        with self.database.session() as session:
            return CourseRepository(session).get(course_id)

    def update_course(self, course_id: int, **values: object) -> object:
        with self.database.session() as session:
            item = CourseRepository(session).get(course_id)
            if not item:
                raise ValueError("课程不存在")
            name = str(values.get("name", item.name)).strip()
            if not name:
                raise ValueError("课程名称不能为空")
            for key, value in values.items():
                if hasattr(item, key):
                    setattr(item, key, value)
            item.name = name
            session.flush()
            return item

    def archive_course(self, course_id: int) -> None:
        with self.database.session() as session:
            CourseRepository(session).archive(course_id)

    def list_today_tasks(self) -> list[object]:
        with self.database.session() as session:
            return TaskRepository(session).list_for_day(date.today())

    def list_tasks(self, start: date, end: date) -> list[object]:
        with self.database.session() as session:
            return TaskRepository(session).list_range(start, end)

    def create_task(
        self, title: str, duration: int, priority: str = "中",
        planned_date: date | None = None, scheduled_time: str = "", note: str = "",
        course_id: int | None = None
    ) -> object:
        if not title.strip():
            raise ValueError("任务名称不能为空")
        with self.database.session() as session:
            return TaskRepository(session).add(
                title=title.strip(), duration_minutes=duration, priority=priority,
                planned_date=planned_date or date.today(), scheduled_time=scheduled_time,
                note=note, course_id=course_id
            )

    def update_task(
        self, task_id: int, title: str, duration: int, priority: str,
        planned_date: date, scheduled_time: str = "", note: str = "",
        course_id: int | None = None
    ) -> object:
        if not title.strip():
            raise ValueError("任务名称不能为空")
        with self.database.session() as session:
            item = TaskRepository(session).get(task_id)
            if not item:
                raise ValueError("任务不存在")
            item.title = title.strip()
            item.duration_minutes = duration
            item.priority = priority
            item.planned_date = planned_date
            item.scheduled_time = scheduled_time
            item.note = note
            item.course_id = course_id
            session.flush()
            return item

    def get_task(self, task_id: int) -> object | None:
        with self.database.session() as session:
            return TaskRepository(session).get(task_id)

    def delete_task(self, task_id: int) -> None:
        with self.database.session() as session:
            TaskRepository(session).delete(task_id)

    def complete_task(self, task_id: int) -> None:
        with self.database.session() as session:
            task = TaskRepository(session).get(task_id)
            if task is None:
                raise ValueError("Task does not exist")
            course_id = task.course_id
            TaskRepository(session).complete(task_id)
        if course_id is not None:
            CourseProgressService(self.database).refresh(course_id)

    def list_goals(self) -> list[object]:
        with self.database.session() as session:
            return GoalRepository(session).list()

    def create_goal(
        self, title: str, target_date: date, weekly_minutes: int,
        target_score: float | None = None, course_id: int | None = None
    ) -> object:
        if not title.strip():
            raise ValueError("目标名称不能为空")
        with self.database.session() as session:
            return GoalRepository(session).add(
                title=title.strip(), target_date=target_date, weekly_minutes=weekly_minutes,
                target_score=target_score, course_id=course_id
            )

    def get_goal(self, goal_id: int) -> object | None:
        with self.database.session() as session:
            return GoalRepository(session).get(goal_id)

    def update_study_goal(
        self, goal_id: int, title: str, target_date: date,
        weekly_minutes: int, progress: int
    ) -> object:
        if not title.strip():
            raise ValueError("目标名称不能为空")
        with self.database.session() as session:
            item = GoalRepository(session).get(goal_id)
            if not item:
                raise ValueError("学习目标不存在")
            item.title = title.strip()
            item.target_date = target_date
            item.weekly_minutes = weekly_minutes
            item.progress = max(0, min(100, progress))
            session.flush()
            return item

    def archive_goal(self, goal_id: int) -> None:
        with self.database.session() as session:
            GoalRepository(session).archive(goal_id)

    def start_study_session(self, task_id: int | None = None, course_id: int | None = None) -> object:
        with self.database.session() as session:
            item = StudySession(task_id=task_id, course_id=course_id, started_at=datetime.now())
            session.add(item)
            session.flush()
            return item

    def finish_study_session(self, session_id: int, duration_minutes: int, note: str = "") -> object:
        with self.database.session() as session:
            item = session.get(StudySession, session_id)
            if not item:
                raise ValueError("学习记录不存在")
            item.ended_at = datetime.now()
            item.duration_minutes = max(1, duration_minutes)
            item.note = note.strip()
            session.flush()
            return item

    @staticmethod
    def distribute_schedule(
        start: date, end: date, task_count: int, minutes_per_task: int, max_daily_minutes: int
    ) -> list[date]:
        if end < start:
            raise ValueError("结束日期不能早于开始日期")
        if task_count <= 0 or minutes_per_task <= 0 or max_daily_minutes < minutes_per_task:
            raise ValueError("任务数量或每日时间限制无效")
        days = [start + timedelta(days=index) for index in range((end - start).days + 1)]
        capacity = max_daily_minutes // minutes_per_task
        if capacity * len(days) < task_count:
            raise ValueError("可用日期与每日时长不足以安排全部任务")
        result: list[date] = []
        remaining = task_count
        for offset, day in enumerate(days):
            remaining_days = len(days) - offset
            today = min(capacity, (remaining + remaining_days - 1) // remaining_days)
            result.extend([day] * today)
            remaining -= today
        return result

    def create_distributed_tasks(
        self, title_prefix: str, start: date, end: date, task_count: int,
        minutes_per_task: int, max_daily_minutes: int, priority: str = "中"
    ) -> list[object]:
        schedule = self.distribute_schedule(start, end, task_count, minutes_per_task, max_daily_minutes)
        created = []
        with self.database.session() as session:
            repo = TaskRepository(session)
            for index, day in enumerate(schedule, 1):
                created.append(repo.add(
                    title=f"{title_prefix} {index}/{task_count}", planned_date=day,
                    duration_minutes=minutes_per_task, priority=priority
                ))
        return created

    def create_recurring_tasks(
        self, title: str, start: date, frequency: str, occurrences: int,
        duration: int, priority: str = "中"
    ) -> list[object]:
        if frequency not in {"daily", "weekly"}:
            raise ValueError("重复频率无效")
        if occurrences < 1 or occurrences > 365:
            raise ValueError("重复次数应为 1 到 365")
        if not title.strip():
            raise ValueError("任务名称不能为空")
        key = f"{frequency}:{start.isoformat()}:{title.strip()}"
        step = 1 if frequency == "daily" else 7
        created = []
        with self.database.session() as session:
            repo = TaskRepository(session)
            existing_days = set(session.scalars(select(StudyTask.planned_date).where(
                StudyTask.recurrence_key == key
            )))
            for index in range(occurrences):
                day = start + timedelta(days=index * step)
                if day not in existing_days:
                    created.append(repo.add(
                        title=title.strip(), planned_date=day, duration_minutes=duration,
                        priority=priority, recurrence_key=key
                    ))
        return created

    def seed_demo(self) -> None:
        with self.database.session() as session:
            if session.scalar(select(Course).where(Course.source == "demo")):
                return
            course = CourseRepository(session).add(
                name="高中数学 · 函数专题", education_stage="高中", subject="数学",
                description="函数、导数与综合题", progress=42, source="demo"
            )
            CourseRepository(session).add(
                name="大学高等数学", education_stage="大学", subject="数学",
                description="微积分基础与应用", progress=26, source="demo"
            )
            CourseRepository(session).add(
                name="国考行测训练", education_stage="职业考试", subject="行测",
                description="数量关系与判断推理", progress=61, source="demo"
            )
            repo = TaskRepository(session)
            repo.add(title="复习函数单调性", course_id=course.id, duration_minutes=30, priority="高", source="demo")
            repo.add(title="完成导数专项练习", course_id=course.id, duration_minutes=45, priority="中", source="demo")
            from app.models import ReviewItem
            session.add(ReviewItem(title="复合函数定义域", next_review=date.today(), wrong_count=2, source="demo"))
            session.add(ReviewItem(title="导数几何意义", next_review=date.today() + timedelta(days=1), source="demo"))

    def clear_demo(self) -> int:
        from sqlalchemy import delete
        from app.models import Question, ReviewItem

        total = 0
        with self.database.session() as session:
            for model in (ReviewItem, Question, StudyTask, Course):
                result = session.execute(delete(model).where(model.source == "demo"))
                total += result.rowcount or 0
        return total
