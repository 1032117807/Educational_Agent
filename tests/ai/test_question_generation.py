from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from ai.chains import (
    GeneratedQuestion,
    QuestionDraftService,
    QuestionGenerationOutput,
    QuestionGenerationService,
)
from ai.retrieval import KnowledgeRetrievalHit, RetrievalHit
from app.database import Database
from app.models import (
    AIRun,
    Course,
    DocumentChunk,
    DocumentIndex,
    KnowledgePoint,
    Question,
    QuestionDraft,
    QuestionDraftCitation,
    ResourceFile,
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


def prepare_evidence(database: Database):
    with database.session() as session:
        course = Course(name="高等数学")
        session.add(course)
        session.flush()
        point = KnowledgePoint(
            course_id=course.id,
            name="函数极限",
            category="定义",
            definition="描述函数值的趋近趋势",
            difficulty=3,
            importance=5,
            confidence=0.9,
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
        session.add_all([point, resource])
        session.flush()
        document_index = DocumentIndex(
            resource_id=resource.id,
            status="completed",
            parser_version="test",
            chunker_version="test",
            embedding_model="test",
            source_sha256=resource.sha256,
            chunk_count=1,
        )
        session.add(document_index)
        session.flush()
        chunk = DocumentChunk(
            document_index_id=document_index.id,
            resource_id=resource.id,
            course_id=course.id,
            chunk_number=0,
            content="函数极限描述函数在某点附近的变化趋势。",
            content_sha256="b" * 64,
            page_start=18,
            page_end=18,
            location_label="第 18 页",
            metadata_json=json.dumps({"source_name": "高数.pdf"}),
            vector_id="vector-1",
        )
        session.add(chunk)
        session.flush()
        knowledge_hit = KnowledgeRetrievalHit(
            knowledge_point_id=point.id,
            course_id=course.id,
            name=point.name,
            category=point.category,
            definition=point.definition,
            formula="",
            prerequisites=(),
            related_points=(),
            common_mistakes=(),
            difficulty=3,
            importance=5,
            confidence=0.9,
            rrf_score=0.03,
            keyword_rank=1,
            semantic_rank=1,
            keyword_score=-1.0,
            semantic_distance=0.1,
        )
        document_hit = RetrievalHit(
            chunk_id=chunk.id,
            resource_id=resource.id,
            document_index_id=document_index.id,
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
        return course.id, point.id, chunk.id, knowledge_hit, document_hit


def test_generate_persist_citations_and_accept(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'questions.db').as_posix()}")
    database.create_schema()
    course_id, point_id, chunk_id, knowledge_hit, document_hit = (
        prepare_evidence(database)
    )
    output = QuestionGenerationOutput(questions=[
        GeneratedQuestion(
            knowledge_point_id=point_id,
            kind="判断",
            prompt="函数极限是否用于描述函数值的变化趋势？",
            answer="是",
            explanation="资料明确给出了这一描述。[D1]",
            difficulty=2,
            document_evidence_numbers=[1],
        )
    ])
    service = QuestionGenerationService(
        database=database,
        knowledge_retriever=FakeRetriever([knowledge_hit]),
        document_retriever=FakeRetriever([document_hit]),
        structured_model=FakeStructuredModel(output),
        provider="test",
        model_name="test-model",
    )

    result = service.generate(
        "函数极限概念辨析",
        course_id=course_id,
        count=1,
        kinds=["判断"],
    )

    assert len(result.draft_ids) == 1
    with database.session() as session:
        draft = session.get(QuestionDraft, result.draft_ids[0])
        citation = session.scalar(select(QuestionDraftCitation))
        run = session.get(AIRun, result.ai_run_id)
        assert draft is not None
        assert draft.knowledge_point_id == point_id
        assert citation.chunk_id == chunk_id
        assert citation.citation_number == 1
        assert run.status == "completed"

    drafts = QuestionDraftService(database)
    views = drafts.list(course_id=course_id)
    assert len(views) == 1
    assert views[0].citations[0].location_label == "第 18 页"
    question_id = drafts.accept(views[0].id)
    with database.session() as session:
        question = session.get(Question, question_id)
        draft = session.get(QuestionDraft, views[0].id)
        assert question.source == "ai"
        assert question.knowledge_point_id == point_id
        assert draft.status == "accepted"
    database.close()


def test_fake_document_citation_fails_run(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'invalid.db').as_posix()}")
    database.create_schema()
    course_id, point_id, _, knowledge_hit, document_hit = prepare_evidence(database)
    output = QuestionGenerationOutput(questions=[
        GeneratedQuestion(
            knowledge_point_id=point_id,
            kind="简答",
            prompt="解释函数极限。",
            answer="描述趋近趋势。",
            explanation="伪造的证据。[D9]",
            difficulty=3,
            document_evidence_numbers=[9],
        )
    ])
    service = QuestionGenerationService(
        database=database,
        knowledge_retriever=FakeRetriever([knowledge_hit]),
        document_retriever=FakeRetriever([document_hit]),
        structured_model=FakeStructuredModel(output),
        provider="test",
        model_name="test-model",
    )

    with pytest.raises(ValueError, match="不存在的文档证据"):
        service.generate("测试", course_id=course_id, kinds=["简答"])

    with database.session() as session:
        run = session.scalar(select(AIRun))
        assert run.status == "failed"
        assert list(session.scalars(select(QuestionDraft))) == []
    database.close()
