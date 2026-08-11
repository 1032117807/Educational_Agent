from datetime import date, datetime

from app.database import Database
from app.models import (
    Course,
    KnowledgePoint,
    PracticeSession,
    Question,
    QuestionAttempt,
    StudySession,
    StudyTask,
)
from app.services.agent_risk import AgentRiskService
from app.services.learning_snapshot import LearningSnapshotService


def test_risk_policy_auto_confirms_or_denies_by_operation():
    service = AgentRiskService()

    assert service.assess_tool("mcp.run_python_in_sandbox").level == "auto"
    network = service.assess_tool("mcp.search_web")
    assert network.level == "confirm"
    assert network.remember_scope == "network_read"
    assert service.assess_tool("mcp.fetch_public_url", {"url": "https://example.com"}).level == "confirm"
    assert service.assess_tool("mcp.write_workspace_file").remember_scope is None
    assert service.assess_tool("mcp.read_workspace_file", {"path": "../secret"}).level == "deny"


def test_learning_snapshot_is_bounded_read_only_and_contains_analysis_records(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'snapshot.db').as_posix()}")
    database.create_schema()
    with database.session() as session:
        course = Course(name="高等数学")
        session.add(course)
        session.flush()
        point = KnowledgePoint(course_id=course.id, name="极限", mastery=35, difficulty=3, importance=4)
        session.add(point)
        session.flush()
        question = Question(course_id=course.id, knowledge_point_id=point.id, prompt="题目", answer="答案", difficulty=3)
        session.add(question)
        session.flush()
        practice = PracticeSession(course_id=course.id, started_at=datetime.now())
        session.add(practice)
        session.flush()
        session.add_all([
            StudySession(course_id=course.id, started_at=datetime.now(), duration_minutes=40, note="不应导出"),
            StudyTask(title="复习极限", course_id=course.id, planned_date=date.today(), duration_minutes=30, completed=True, note="不应导出"),
            QuestionAttempt(session_id=practice.id, question_id=question.id, correct=False, elapsed_seconds=45),
        ])

    payload = LearningSnapshotService(database).build(days=30, course_id=course.id)

    assert payload["scope"] == "read_only_learning_snapshot"
    assert payload["study_sessions"] == [{"date": date.today().isoformat(), "duration_minutes": 40, "course_id": course.id}]
    assert payload["tasks"][0]["completed"] is True
    assert payload["attempts"][0]["correct"] is False
    assert payload["knowledge_points"][0]["name"] == "极限"
    assert "note" not in payload["study_sessions"][0]
    database.close()
