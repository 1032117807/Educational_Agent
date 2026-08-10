from datetime import date, datetime, timedelta
from pathlib import Path

from ai.reports import LearningReport, LearningReportService, ReportExplanation, render_learning_report
from app.database import Database
from app.models import Course, KnowledgePoint, QuestionAttempt, StudySession, StudyTask
from app.services.skill_script_runner import SkillScriptRunner


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


def test_report_snapshot_is_saved_and_listed(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'report.db').as_posix()}")
    db.create_schema()
    service = LearningReportService.__new__(LearningReportService)
    service.database = db
    report = LearningReport(
        stats=service.calculate_stats(start_date=date(2026, 1, 1), end_date=date(2026, 1, 7)),
        explanation=ReportExplanation(summary="测试总结"),
    )
    markdown = render_learning_report(report)
    saved = service.save_snapshot(report, markdown)
    reports = service.list_snapshots()
    assert saved.id == reports[0].id
    assert reports[0].markdown == markdown
    assert "测试总结" in reports[0].markdown
    db.close()


def test_visualization_service_writes_local_svg_charts(tmp_path):
    db = Database(f"sqlite:///{(tmp_path / 'report.db').as_posix()}")
    db.create_schema()
    service = LearningReportService.__new__(LearningReportService)
    service.database = db
    stats = service.calculate_stats(start_date=date(2026, 1, 1), end_date=date(2026, 1, 7))
    service.chart_output_dir = tmp_path / "charts"
    service.skill_runner = SkillScriptRunner()
    charts = tuple(map(Path, service._render_charts(stats)))

    assert len(charts) == 2
    assert all(path.is_file() and "<svg" in path.read_text(encoding="utf-8") for path in charts)
    report = LearningReport(stats=stats, explanation=ReportExplanation(summary="summary"), chart_paths=tuple(map(str, charts)))
    assert "![" in render_learning_report(report)
    db.close()
