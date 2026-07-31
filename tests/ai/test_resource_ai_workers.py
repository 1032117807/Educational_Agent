from __future__ import annotations

from dataclasses import dataclass

from ai.chains import QuestionGenerationResult, RAGAnswer
from app.database import Database
from app.services.domain import JobService
from app.ui.resource_qa_widget import QAWorker
from app.ui.resources_page import ResourceIndexWorker
from app.ui.question_generation_widget import QuestionGenerationWorker


class FakeQAService:
    def ask(
        self,
        question: str,
        *,
        course_id: int | None = None,
        resource_ids: list[int] | None = None,
    ) -> RAGAnswer:
        assert question == "什么是极限？"
        assert course_id is None
        assert resource_ids is None
        return RAGAnswer(
            ai_run_id=1,
            answer="当前证据不足。",
            citations=(),
            insufficient_evidence=True,
        )


@dataclass(frozen=True)
class FakeIndexResult:
    chunk_count: int = 12
    vector_count: int = 12


class FakeIndexingPipeline:
    def index_resource(self, resource_id: int, **kwargs) -> FakeIndexResult:
        assert resource_id == 7
        kwargs["progress"](100)
        assert kwargs["should_cancel"]() is False
        return FakeIndexResult()


class FakeQuestionGenerationService:
    def generate(self, request: str, **kwargs) -> QuestionGenerationResult:
        assert request == "生成极限判断题"
        assert kwargs["course_id"] == 3
        assert kwargs["count"] == 2
        assert kwargs["kinds"] == ["判断"]
        assert kwargs["difficulty"] == 2
        assert kwargs["resource_ids"] == [9]
        return QuestionGenerationResult(
            ai_run_id=4,
            draft_ids=(11, 12),
            knowledge_hit_count=2,
            document_hit_count=5,
        )


def test_qa_worker_completes_background_job(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'qa-worker.db').as_posix()}")
    database.create_schema()
    jobs = JobService(database)
    job = jobs.create(
        "document_qa",
        "测试问答",
        payload='{"question":"什么是极限？"}',
    )
    worker = QAWorker(
        qa_factory=lambda: FakeQAService(),
        jobs=jobs,
        job_id=job.id,
        question="什么是极限？",
        course_id=None,
        resource_ids=None,
    )

    worker.run()

    saved = jobs.get(job.id)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.progress == 100
    assert saved.payload == '{"question":"什么是极限？"}'
    database.close()


def test_index_worker_completes_background_job(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'index-worker.db').as_posix()}")
    database.create_schema()
    jobs = JobService(database)
    job = jobs.create(
        "document_index",
        "测试索引",
        payload='{"resource_id":7,"force":false}',
    )
    worker = ResourceIndexWorker(
        pipeline_factory=lambda: FakeIndexingPipeline(),
        jobs=jobs,
        job_id=job.id,
        resource_id=7,
        force=False,
    )

    worker.run()

    saved = jobs.get(job.id)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.progress == 100
    assert "12 个片段" in saved.detail
    database.close()


def test_question_generation_worker_completes_job(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'question-worker.db').as_posix()}")
    database.create_schema()
    jobs = JobService(database)
    job = jobs.create("question_generation", "测试 AI 出题")
    worker = QuestionGenerationWorker(
        service_factory=lambda: FakeQuestionGenerationService(),
        jobs=jobs,
        job_id=job.id,
        request="生成极限判断题",
        course_id=3,
        count=2,
        kinds=["判断"],
        difficulty=2,
        resource_ids=[9],
    )

    worker.run()

    saved = jobs.get(job.id)
    assert saved is not None
    assert saved.status == "completed"
    assert saved.progress == 100
    assert "2 道待审核题目" in saved.detail
    database.close()
