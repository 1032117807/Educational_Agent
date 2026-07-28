from __future__ import annotations

from uuid import uuid4

from sqlalchemy import inspect, select

from app.database import Database
from app.models import (
    AICitation,
    AIRun,
    Course,
    DocumentChunk,
    DocumentIndex,
    KnowledgePointDraft,
    QuestionDraft,
    ResourceFile,
)


EXPECTED_AI_TABLES = {
    "ai_citations",
    "ai_runs",
    "document_chunks",
    "document_indexes",
    "knowledge_point_drafts",
    "question_drafts",
}


def test_create_schema_creates_all_ai_tables(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'ai-schema.db').as_posix()}")
    database.create_schema()

    tables = set(inspect(database.engine).get_table_names())

    assert EXPECTED_AI_TABLES <= tables
    database.close()


def test_ai_records_preserve_traceability(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'trace.db').as_posix()}")
    database.create_schema()

    with database.session() as session:
        course = Course(
            name="高等数学",
            description="",
            subject="数学",
        )
        session.add(course)
        session.flush()

        resource = ResourceFile(
            name="chapter-1.pdf",
            original_name="第一章.pdf",
            source_path="",
            relative_path="chapter-1.pdf",
            sha256="a" * 64,
            size=1024,
            course_id=course.id,
        )
        session.add(resource)
        session.flush()

        document_index = DocumentIndex(
            resource_id=resource.id,
            status="completed",
            parser_version="pymupdf-v1",
            chunker_version="recursive-v1",
            embedding_model="test-embedding",
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
            content="函数极限描述函数在某个变化过程中的趋势。",
            content_sha256="b" * 64,
            page_start=18,
            page_end=18,
            location_label="第 18 页",
            vector_id="chunk-test-1",
        )
        session.add(chunk)
        session.flush()

        ai_run = AIRun(
            run_uuid=str(uuid4()),
            feature="document_qa",
            status="completed",
            provider="test",
            model_name="test-model",
            prompt_version="qa-v1",
            input_json='{"question": "什么是函数极限？"}',
            output_json='{"answer": "函数极限描述变化趋势。"}',
            course_id=course.id,
        )
        session.add(ai_run)
        session.flush()

        citation = AICitation(
            ai_run_id=ai_run.id,
            chunk_id=chunk.id,
            citation_number=1,
            quote_text=chunk.content,
            relevance_score=0.95,
        )
        session.add(citation)

        knowledge_draft = KnowledgePointDraft(
            ai_run_id=ai_run.id,
            course_id=course.id,
            name="函数极限",
            definition="描述函数的变化趋势。",
        )
        session.add(knowledge_draft)

        question_draft = QuestionDraft(
            ai_run_id=ai_run.id,
            course_id=course.id,
            kind="简答",
            prompt="说明函数极限的含义。",
            answer="函数极限用于描述函数在变化过程中的趋势。",
        )
        session.add(question_draft)

    with database.session() as session:
        saved_chunk = session.scalar(select(DocumentChunk))
        saved_citation = session.scalar(select(AICitation))
        saved_knowledge = session.scalar(select(KnowledgePointDraft))
        saved_question = session.scalar(select(QuestionDraft))

        assert saved_chunk is not None
        assert saved_chunk.page_start == 18
        assert saved_chunk.location_label == "第 18 页"

        assert saved_citation is not None
        assert saved_citation.chunk_id == saved_chunk.id
        assert saved_citation.relevance_score == 0.95

        assert saved_knowledge is not None
        assert saved_knowledge.status == "pending"
        assert saved_knowledge.accepted_knowledge_point_id is None

        assert saved_question is not None
        assert saved_question.status == "pending"
        assert saved_question.accepted_question_id is None

    database.close()