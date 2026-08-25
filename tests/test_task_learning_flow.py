from datetime import date

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models import Course, KnowledgePoint, Question, StudyTask, TaskAssignment
from server.deps import RequestContext
from server.routers import (
    PracticeAttemptRequest, TaskActionRequest, act_on_task, complete_practice_session,
    get_task_learning, start_task_practice, submit_practice_attempt,
)


def test_task_requires_assigned_practice_and_completes_from_result(tmp_path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'task-learning.db').as_posix()}")
    Base.metadata.create_all(engine)
    context = RequestContext(user_id="user-a", tenant_id="tenant-a", role="member")
    with sessionmaker(engine)() as session:
        course = Course(tenant_id="tenant-a", name="English")
        session.add(course); session.flush()
        point = KnowledgePoint(tenant_id="tenant-a", course_id=course.id, name="Main idea", definition="Find the central claim.")
        question = Question(tenant_id="tenant-a", course_id=course.id, knowledge_point_id=None, prompt="Choose A", answer="A", kind="single_choice", options="A\nB")
        task = StudyTask(tenant_id="tenant-a", course_id=course.id, title="Read and practise", planned_date=date.today(), duration_minutes=30)
        session.add_all([point, question, task]); session.flush()
        session.add_all([
            TaskAssignment(tenant_id="tenant-a", task_id=task.id, knowledge_point_id=point.id, position=1),
            TaskAssignment(tenant_id="tenant-a", task_id=task.id, question_id=question.id, position=2),
        ])
        session.commit()

        payload = get_task_learning(task.id, context, session)
        assert payload["knowledge"][0]["name"] == "Main idea"
        assert payload["questions"][0]["id"] == question.id
        with pytest.raises(HTTPException) as blocked:
            act_on_task(task.id, TaskActionRequest(action="complete"), context, session)
        assert blocked.value.status_code == 409

        practice = start_task_practice(task.id, context, session)
        submit_practice_attempt(practice["id"], question.id, PracticeAttemptRequest(response="A", elapsed_seconds=1), context, session)
        result = complete_practice_session(practice["id"], context, session)
        assert result["task_result"] == {"task_id": task.id, "completed": True, "accuracy": 100.0}
        assert session.get(StudyTask, task.id).completed is True
