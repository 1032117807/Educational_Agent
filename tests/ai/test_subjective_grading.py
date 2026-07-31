from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from ai.chains import (
    CriterionGrade,
    SubjectiveGradeOutput,
    SubjectiveGradingService,
)
from ai.retrieval import RetrievalHit
from app.database import Database
from app.models import (
    AICitation,
    AIRun,
    Course,
    DocumentChunk,
    DocumentIndex,
    KnowledgePoint,
    PracticeSession,
    Question,
    QuestionAttempt,
    ResourceFile,
    SubjectiveGradingCitation,
    SubjectiveGradingResult,
)


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits

    def retrieve(self, _query, **_kwargs):
        return self.hits


class FakeStructuredModel:
    def __init__(self, output):
        self.output = output

    def invoke(self, _input):
        return self.output


def prepare_attempt(database: Database):
    with database.session() as session:
        course = Course(name="高等数学")
        session.add(course)
        session.flush()
        knowledge = KnowledgePoint(
            course_id=course.id,
            name="函数极限",
            definition="描述函数值的趋近趋势",
            source="ai",
        )
        resource = ResourceFile(
            name="高数.pdf",
            original_name="高数.pdf",
            relative_path="高数.pdf",
            sha256="a" * 64,
            size=100,
            course_id=course.id,
        )
        session.add_all([knowledge, resource])
        session.flush()
        index = DocumentIndex(
            resource_id=resource.id,
            status="completed",
            parser_version="test",
            chunker_version="test",
            embedding_model="test",
            source_sha256=resource.sha256,
            chunk_count=1,
        )
        session.add(index)
        session.flush()
        chunk = DocumentChunk(
            document_index_id=index.id,
            resource_id=resource.id,
            course_id=course.id,
            chunk_number=0,
            content="函数极限用于描述函数值在变化过程中的趋近趋势。",
            content_sha256="b" * 64,
            page_start=18,
            page_end=18,
            location_label="第 18 页",
            metadata_json=json.dumps({"source_name": "高数.pdf"}),
            vector_id="vector-1",
        )
        question = Question(
            course_id=course.id,
            knowledge_point_id=knowledge.id,
            kind="简答",
            prompt="什么是函数极限？",
            answer="函数极限描述函数值的趋近趋势。",
            source="ai",
        )
        practice = PracticeSession(course_id=course.id, total=1)
        session.add_all([chunk, question, practice])
        session.flush()
        attempt = QuestionAttempt(
            session_id=practice.id,
            question_id=question.id,
            response="函数极限反映函数值逐渐接近某个值的趋势。",
        )
        session.add(attempt)
        session.flush()
        hit = RetrievalHit(
            chunk_id=chunk.id,
            resource_id=resource.id,
            document_index_id=index.id,
            source_name="高数.pdf",
            content=chunk.content,
            retrieval_text=chunk.content,
            location_label=chunk.location_label,
            section_title="函数极限",
            page_start=18,
            page_end=18,
            line_start=None,
            line_end=None,
            rrf_score=0.03,
            keyword_rank=1,
            semantic_rank=1,
            keyword_score=-1.0,
            semantic_distance=0.1,
            metadata={},
        )
        return attempt.id, chunk.id, hit


def valid_output() -> SubjectiveGradeOutput:
    return SubjectiveGradeOutput(
        criterion_grades=[
            CriterionGrade(
                name="核心概念", score=45,
                feedback="核心含义正确。[D1]", evidence_numbers=[1],
            ),
            CriterionGrade(
                name="推理过程", score=25,
                feedback="表达基本连贯。[D1]", evidence_numbers=[1],
            ),
            CriterionGrade(
                name="完整性", score=15,
                feedback="可以进一步说明变化过程。[D1]", evidence_numbers=[1],
            ),
        ],
        total_score=85,
        strengths=["正确说明了趋近趋势"],
        missing_points=["没有明确说明变化过程。[D1]"],
        errors=[],
        feedback="答案抓住了核心概念，但还可以更完整。[D1]",
        improved_answer="函数极限描述函数值在变化过程中的趋近趋势。[D1]",
        confidence=0.9,
        needs_human_review=False,
        used_evidence_numbers=[1],
    )


def test_grade_persists_scores_citations_and_human_review(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'grading.db').as_posix()}")
    database.create_schema()
    attempt_id, chunk_id, hit = prepare_attempt(database)
    service = SubjectiveGradingService(
        database=database,
        document_retriever=FakeRetriever([hit]),
        structured_model=FakeStructuredModel(valid_output()),
        provider="test",
        model_name="test-model",
    )

    result = service.grade_attempt(attempt_id)

    assert result.total_score == 85
    assert result.max_score == 100
    assert result.citations[0].chunk_id == chunk_id
    with database.session() as session:
        stored = session.get(SubjectiveGradingResult, result.grading_result_id)
        citation = session.scalar(select(SubjectiveGradingCitation))
        ai_citation = session.scalar(select(AICitation))
        run = session.get(AIRun, result.ai_run_id)
        assert stored.status == "completed"
        assert citation.chunk_id == chunk_id
        assert ai_citation.chunk_id == chunk_id
        assert run.status == "completed"

    service.apply_human_review(
        result.grading_result_id, score=88, note="人工确认"
    )
    with database.session() as session:
        stored = session.get(SubjectiveGradingResult, result.grading_result_id)
        assert stored.human_score == 88
        assert stored.status == "human_reviewed"
    database.close()


def test_invalid_score_sum_fails_run(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'invalid.db').as_posix()}")
    database.create_schema()
    attempt_id, _, hit = prepare_attempt(database)
    output = valid_output()
    output.total_score = 90
    service = SubjectiveGradingService(
        database=database,
        document_retriever=FakeRetriever([hit]),
        structured_model=FakeStructuredModel(output),
        provider="test",
        model_name="test-model",
    )

    with pytest.raises(ValueError, match="分项得分之和"):
        service.grade_attempt(attempt_id)

    with database.session() as session:
        run = session.scalar(select(AIRun))
        assert run.status == "failed"
        assert list(session.scalars(select(SubjectiveGradingResult))) == []
    database.close()


def test_low_confidence_requires_human_review(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'confidence.db').as_posix()}")
    database.create_schema()
    attempt_id, _, hit = prepare_attempt(database)
    output = valid_output()
    output.confidence = 0.5
    output.needs_human_review = False
    service = SubjectiveGradingService(
        database=database,
        document_retriever=FakeRetriever([hit]),
        structured_model=FakeStructuredModel(output),
        provider="test",
        model_name="test-model",
    )

    with pytest.raises(ValueError, match="低置信度"):
        service.grade_attempt(attempt_id)
    database.close()
