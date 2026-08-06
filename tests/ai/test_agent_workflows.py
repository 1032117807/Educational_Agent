from app.database import Database
from app.models import AgentHandoff, AgentSession, Course, ResourceFile
from app.services.agent_workflows import AgentWorkflowService


class FakeIndexingPipeline:
    def __init__(self) -> None:
        self.indexed: list[int] = []

    def index_resource(self, resource_id: int, **_kwargs):
        self.indexed.append(resource_id)


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
