from app.database import Database
import json

import pytest

from ai.agents.specialists import SpecialistResult
from app.models import AgentHandoff, AgentSession, Course, KnowledgePoint, KnowledgePointDraft, ResourceFile
from app.services.cancellation import CancellationToken, OperationCancelled
from app.services.agent_workflows import AgentWorkflowService


class FakeIndexingPipeline:
    def __init__(self) -> None:
        self.indexed: list[int] = []

    def index_resource(self, resource_id: int, **_kwargs):
        self.indexed.append(resource_id)


class FakeWorkflowOrchestrator:
    """Deterministic stand-in for a real course run without an external model."""

    def __init__(self, *, fail_once: bool = False) -> None:
        self.calls: list[str] = []
        self.fail_once = fail_once

    def run(self, step, _context, _progress=None, should_cancel=None):
        self.calls.append(step)
        if should_cancel and should_cancel():
            raise InterruptedError("cancelled by test")
        if self.fail_once and step == "analyze":
            self.fail_once = False
            raise RuntimeError("temporary index failure")
        results = {
            "analyze": SpecialistResult("resource", "indexed", {"indexed_resource_ids": [1]}),
            "extract": SpecialistResult("knowledge", "drafted", {"knowledge_ai_run_id": 1, "knowledge_draft_count": 1}),
            "questions": SpecialistResult("questions", "generated", {"question_ids": [101], "question_draft_ids": [201]}),
            "report": SpecialistResult("report", "reported", {"report_snapshot_id": 301}),
        }
        return results[step]


def _workflow_service(database, orchestrator):
    return AgentWorkflowService(
        database=database,
        indexing_factory=lambda: FakeIndexingPipeline(),
        extraction_factory=lambda: None,
        question_factory=lambda: None,
        report_factory=lambda: None,
        orchestrator=orchestrator,
    )


def _seed_course_workflow(database):
    with database.session() as session:
        course = Course(name="Calculus")
        session.add(course)
        session.flush()
        session.add(AgentSession(title="Course workflow"))
        session.add(ResourceFile(
            name="derivatives.md", relative_path="derivatives.md", sha256="b" * 64,
            size=1, course_id=course.id,
        ))
        return course.id


def _accept_extracted_draft(database, course_id):
    with database.session() as session:
        point = KnowledgePoint(course_id=course_id, name="Derivative")
        session.add(point)
        session.flush()
        session.add(KnowledgePointDraft(
            ai_run_id=1, course_id=course_id, name="Derivative", status="accepted",
            accepted_knowledge_point_id=point.id,
        ))


def test_workflow_persists_analysis_step_and_can_be_cancelled(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'workflow.db').as_posix()}")
    database.create_schema()
    with database.session() as session:
        course = Course(name="Math")
        session.add(course)
        session.flush()
        session.add(AgentSession(title="Agent 1"))
        session.add(ResourceFile(
            name="notes.txt", relative_path="notes.txt", sha256="a" * 64,
            size=1, course_id=course.id,
        ))

    pipeline = FakeIndexingPipeline()
    service = AgentWorkflowService(
        database=database,
        indexing_factory=lambda: pipeline,
        extraction_factory=lambda: None,
        question_factory=lambda: None,
        report_factory=lambda: None,
    )
    workflow = service.create(session_id=1, course_id=1, request="Review notes")
    outcome = service.continue_workflow(workflow.id)

    assert pipeline.indexed == [1]
    assert outcome.step == "extract"
    assert outcome.status == "waiting_confirmation"
    with database.session() as session:
        records = list(session.query(AgentHandoff).all())
    assert any(
        '"to_agent": "资料分析 Agent"' in record.payload_json
        and '"input_summary"' in record.payload_json
        for record in records
    )
    assert service.latest_for_session(1).id == workflow.id
    assert service.cancel(workflow.id).status == "cancelled"
    assert service.latest_for_session(1) is None
    database.close()


def test_complete_course_workflow_can_resume_after_review_and_complete(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'complete-workflow.db').as_posix()}")
    database.create_schema()
    course_id = _seed_course_workflow(database)
    orchestrator = FakeWorkflowOrchestrator()
    service = _workflow_service(database, orchestrator)

    workflow = service.create(session_id=1, course_id=course_id, request="Practice derivatives")
    assert service.continue_workflow(workflow.id).step == "extract"
    assert service.continue_workflow(workflow.id).status == "waiting_review"
    _accept_extracted_draft(database, course_id)
    assert service.confirm_knowledge_review(workflow.id).step == "questions"
    assert service.continue_workflow(workflow.id).step == "practice"
    assert service.question_ids(workflow.id) == [101]
    assert service.mark_practice_complete(workflow.id).step == "report"
    assert service.continue_workflow(workflow.id).status == "completed"
    assert orchestrator.calls == ["analyze", "extract", "questions", "report"]
    assert service.latest_for_session(1) is None
    database.close()


def test_workflow_failure_is_retryable_and_cancellation_is_durable(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'retry-workflow.db').as_posix()}")
    database.create_schema()
    course_id = _seed_course_workflow(database)
    orchestrator = FakeWorkflowOrchestrator(fail_once=True)
    service = _workflow_service(database, orchestrator)
    workflow = service.create(session_id=1, course_id=course_id, request="Practice derivatives")

    with pytest.raises(RuntimeError, match="temporary index failure"):
        service.continue_workflow(workflow.id)
    assert service.get(workflow.id).status == "failed"
    assert service.continue_workflow(workflow.id).step == "extract"
    assert orchestrator.calls == ["analyze", "analyze"]

    token = CancellationToken()
    token.cancel("window is closing")
    with pytest.raises(OperationCancelled, match="window is closing"):
        service.continue_workflow(workflow.id, cancellation=token)
    assert service.get(workflow.id).status == "cancelled"
    database.close()


def test_workflow_resume_reuses_persisted_question_artifact_without_regeneration(tmp_path):
    database = Database(f"sqlite:///{(tmp_path / 'idempotent-workflow.db').as_posix()}")
    database.create_schema()
    course_id = _seed_course_workflow(database)
    orchestrator = FakeWorkflowOrchestrator()
    service = _workflow_service(database, orchestrator)
    workflow = service.create(session_id=1, course_id=course_id, request="Practice derivatives")

    with database.session() as session:
        item = session.get(type(workflow), workflow.id)
        item.current_step = "questions"
        item.status = "failed"
        item.context_json = json.dumps({"resource_ids": [1], "question_ids": [101]})

    restored = _workflow_service(database, orchestrator)
    outcome = restored.continue_workflow(workflow.id)
    assert outcome.step == "practice"
    assert outcome.payload["question_ids"] == [101]
    assert orchestrator.calls == []
    database.close()
