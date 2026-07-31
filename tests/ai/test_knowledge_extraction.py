from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from ai.chains import (
    ExtractedKnowledgePoint,
    KnowledgeDraftService,
    KnowledgeExtractionOutput,
    KnowledgeExtractionService,
)
from app.database import Database
from app.models import (
    AICitation,
    AIRun,
    Course,
    DocumentChunk,
    DocumentIndex,
    KnowledgePoint,
    KnowledgePointDraft,
    KnowledgePointDraftCitation,
    ResourceFile,
)


class SequenceModel:
    def __init__(self, outputs):
        self.outputs = iter(outputs)

    def invoke(self, _input):
        return next(self.outputs)


def prepare_chunks(database: Database) -> tuple[int, list[int]]:
    with database.session() as session:
        course = Course(name="高等数学")
        session.add(course)
        session.flush()
        resource = ResourceFile(
            name="高数.pdf",
            original_name="高数.pdf",
            relative_path="高数.pdf",
            sha256="a" * 64,
            size=100,
            course_id=course.id,
        )
        session.add(resource)
        session.flush()
        index = DocumentIndex(
            resource_id=resource.id,
            status="completed",
            parser_version="test",
            chunker_version="test",
            embedding_model="test",
            source_sha256=resource.sha256,
            chunk_count=2,
        )
        session.add(index)
        session.flush()
        ids = []
        for number, (content, page) in enumerate((
            ("函数在某点附近的变化趋势可用极限描述。", 18),
            ("函数极限是后续连续性学习的基础。", 19),
        )):
            chunk = DocumentChunk(
                document_index_id=index.id,
                resource_id=resource.id,
                course_id=course.id,
                chunk_number=number,
                content=content,
                content_sha256=str(number + 1) * 64,
                page_start=page,
                page_end=page,
                location_label=f"第 {page} 页",
                metadata_json=json.dumps({"source_name": "高数.pdf"}),
                vector_id=f"vector-{number}",
            )
            session.add(chunk)
            session.flush()
            ids.append(chunk.id)
        return course.id, ids


def point(definition: str, *, evidence: int = 1) -> KnowledgeExtractionOutput:
    return KnowledgeExtractionOutput(knowledge_points=[
        ExtractedKnowledgePoint(
            name="函数极限",
            category="定义",
            definition=definition,
            prerequisites=["函数"],
            related_points=["连续性"],
            common_mistakes=["把函数值等同于极限值"],
            difficulty=3,
            importance=5,
            confidence=0.9,
            evidence_numbers=[evidence],
        )
    ])


def test_extract_merge_cite_and_accept(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'knowledge.db').as_posix()}")
    database.create_schema()
    course_id, chunk_ids = prepare_chunks(database)
    model = SequenceModel([
        point("极限描述函数值的变化趋势。"),
        point("函数极限描述函数在某点附近的变化趋势。"),
    ])
    service = KnowledgeExtractionService(
        database=database,
        structured_model=model,
        provider="test",
        model_name="test-model",
        batch_size=1,
    )

    result = service.extract(course_id=course_id)

    assert result.draft_count == 1
    assert result.chunk_count == 2
    with database.session() as session:
        draft = session.scalar(select(KnowledgePointDraft))
        links = list(session.scalars(select(KnowledgePointDraftCitation)))
        run_citations = list(session.scalars(select(AICitation)))
        assert draft is not None
        assert draft.definition == "函数极限描述函数在某点附近的变化趋势。"
        assert {link.chunk_id for link in links} == set(chunk_ids)
        assert {link.chunk_id for link in run_citations} == set(chunk_ids)

    drafts = KnowledgeDraftService(database)
    views = drafts.list(course_id=course_id)
    assert len(views) == 1
    assert len(views[0].citations) == 2
    knowledge_id = drafts.accept(views[0].id)

    with database.session() as session:
        knowledge = session.get(KnowledgePoint, knowledge_id)
        draft = session.get(KnowledgePointDraft, views[0].id)
        run = session.get(AIRun, result.ai_run_id)
        assert knowledge is not None
        assert knowledge.source == "ai"
        assert knowledge.category == "定义"
        assert draft.status == "accepted"
        assert run.user_confirmed is True
    database.close()


def test_extract_uses_resources_current_course_assignment(tmp_path) -> None:
    database = Database(
        f"sqlite:///{(tmp_path / 'reassigned.db').as_posix()}"
    )
    database.create_schema()
    course_id, _ = prepare_chunks(database)
    with database.session() as session:
        chunks = list(session.scalars(select(DocumentChunk)))
        for chunk in chunks:
            chunk.course_id = None

    service = KnowledgeExtractionService(
        database=database,
        structured_model=SequenceModel([point("定义"), point("定义")]),
        provider="test",
        model_name="test-model",
        batch_size=1,
    )

    result = service.extract(course_id=course_id)

    assert result.chunk_count == 2
    database.close()


def test_invalid_evidence_number_fails_run(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'invalid.db').as_posix()}")
    database.create_schema()
    course_id, _ = prepare_chunks(database)
    service = KnowledgeExtractionService(
        database=database,
        structured_model=SequenceModel([point("错误引用", evidence=2)]),
        provider="test",
        model_name="test-model",
        batch_size=1,
    )

    with pytest.raises(ValueError, match="不存在的证据编号"):
        service.extract(course_id=course_id)

    with database.session() as session:
        run = session.scalar(select(AIRun))
        drafts = list(session.scalars(select(KnowledgePointDraft)))
        assert run.status == "failed"
        assert drafts == []
    database.close()
