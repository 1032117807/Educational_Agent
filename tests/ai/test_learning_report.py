from datetime import date, datetime, timedelta

from ai.reports import LearningReportService
from app.database import Database
from app.models import Course, KnowledgePoint, QuestionAttempt, StudySession, StudyTask


def test_empty_period_returns_zero_metrics(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'report.db').as_posix()}")
    db.create_schema()
    service = LearningReportService.__new__(LearningReportService)
    service.database = db
    stats = service.calculate_stats(
        start_date=date(2026, 1, 1), end_date=date(2026, 1, 7)
    )
    assert stats.study_minutes == 0
    assert stats.accuracy == 0
    assert stats.task_completion_rate == 0
    db.close()


def test_stats_are_calculated_from_database(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'report.db').as_posix()}")
    db.create_schema()
    day = date(2026, 1, 2)
    with db.session() as session:
        course = Course(name="数学")
        session.add(course)
        session.flush()
        session.add(KnowledgePoint(course_id=course.id, name="极限", mastery=20))
        session.add(StudySession(started_at=datetime(2026, 1, 2, 9), duration_minutes=45))
        session.add(StudyTask(title="复习极限", planned_date=day, completed=True))
        session.add_all([
            QuestionAttempt(session_id=1, question_id=1, attempted_at=datetime(2026, 1, 2, 10), correct=True),
            QuestionAttempt(session_id=1, question_id=2, attempted_at=datetime(2026, 1, 2, 10), correct=False),
        ])
    service = LearningReportService.__new__(LearningReportService)
    service.database = db
    stats = service.calculate_stats(start_date=day, end_date=day)
    assert stats.study_minutes == 45
    assert stats.task_completion_rate == 1
    assert stats.accuracy == 0.5
    db.close()
