from __future__ import annotations

import json

import pytest
from sqlalchemy import select

from ai.chains import GroundedAnswer, GroundedQAService
from ai.exceptions import CitationValidationError
from ai.retrieval import RetrievalHit
from app.database import Database
from app.models import (
    AICitation,
    AIRun,
    DocumentChunk,
    DocumentIndex,
    ResourceFile,
)


class FakeRetriever:
    def __init__(self, hits):
        self.hits = hits

    def retrieve(self, query, **kwargs):
        return self.hits


class FakeStructuredModel:
    def __init__(self, answer: GroundedAnswer):
        self.answer = answer
        self.called = False

    def invoke(self, input):
        self.called = True
        return self.answer


def prepare_hit(database: Database) -> RetrievalHit:
    with database.session() as session:
        resource = ResourceFile(
            name="高等数学.pdf",
            original_name="高等数学.pdf",
            source_path="",
            relative_path="高等数学.pdf",
            sha256="a" * 64,
            size=100,
            tags="",
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
            chunk_count=1,
        )
        session.add(index)
        session.flush()

        chunk = DocumentChunk(
            document_index_id=index.id,
            resource_id=resource.id,
            chunk_number=0,
            content="函数极限描述函数值在变化过程中的趋势。",
            content_sha256="b" * 64,
            page_start=18,
            page_end=18,
            location_label="第 18 页",
            metadata_json=json.dumps({
                "source_name": "高等数学.pdf",
                "retrieval_text": (
                    "函数 极限 描述 函数值 在 变化过程 中的 趋势"
                ),
            }, ensure_ascii=False),
            vector_id="vector-1",
        )
        session.add(chunk)
        session.flush()

        return RetrievalHit(
            chunk_id=chunk.id,
            resource_id=resource.id,
            document_index_id=index.id,
            source_name="高等数学.pdf",
            content=chunk.content,
            retrieval_text=chunk.content,
            location_label="第 18 页",
            section_title="函数极限",
            page_start=18,
            page_end=18,
            line_start=None,
            line_end=None,
            rrf_score=0.032,
            keyword_rank=1,
            semantic_rank=1,
            keyword_score=-2.0,
            semantic_distance=0.1,
            metadata={},
        )


def test_valid_citation_is_persisted(tmp_path) -> None:
    database = Database(
        f"sqlite:///{(tmp_path / 'qa.db').as_posix()}"
    )
    database.create_schema()
    hit = prepare_hit(database)

    model = FakeStructuredModel(
        GroundedAnswer(
            answer="函数极限描述函数值的变化趋势。[1]",
            citation_numbers=[1],
            insufficient_evidence=False,
        )
    )

    service = GroundedQAService(
        database=database,
        retriever=FakeRetriever([hit]),
        structured_model=model,
        provider="test",
        model_name="test-model",
    )

    result = service.ask("什么是函数极限？")

    assert result.answer.endswith("[1]")
    assert len(result.citations) == 1
    assert result.citations[0].chunk_id == hit.chunk_id
    assert result.citations[0].citation_label == (
        "高等数学.pdf，第 18 页"
    )

    with database.session() as session:
        run = session.get(AIRun, result.ai_run_id)
        citations = list(
            session.scalars(
                select(AICitation).where(
                    AICitation.ai_run_id == result.ai_run_id
                )
            )
        )

        assert run is not None
        assert run.status == "completed"
        assert len(citations) == 1
        assert citations[0].chunk_id == hit.chunk_id
        assert citations[0].citation_number == 1

    database.close()


def test_fake_citation_number_is_rejected(tmp_path) -> None:
    database = Database(
        f"sqlite:///{(tmp_path / 'invalid.db').as_posix()}"
    )
    database.create_schema()
    hit = prepare_hit(database)

    model = FakeStructuredModel(
        GroundedAnswer(
            answer="这是一个伪造引用。[99]",
            citation_numbers=[99],
            insufficient_evidence=False,
        )
    )

    service = GroundedQAService(
        database=database,
        retriever=FakeRetriever([hit]),
        structured_model=model,
        provider="test",
        model_name="test-model",
    )

    with pytest.raises(CitationValidationError):
        service.ask("测试问题")

    with database.session() as session:
        run = session.scalar(
            select(AIRun).order_by(AIRun.id.desc())
        )
        citations = list(session.scalars(select(AICitation)))

        assert run is not None
        assert run.status == "failed"
        assert citations == []

    database.close()


def test_no_evidence_skips_model_call(tmp_path) -> None:
    database = Database(
        f"sqlite:///{(tmp_path / 'empty.db').as_posix()}"
    )
    database.create_schema()

    model = FakeStructuredModel(
        GroundedAnswer(
            answer="不应被调用",
            citation_numbers=[],
            insufficient_evidence=True,
        )
    )

    service = GroundedQAService(
        database=database,
        retriever=FakeRetriever([]),
        structured_model=model,
        provider="test",
        model_name="test-model",
    )

    result = service.ask("资料中不存在的问题")

    assert result.insufficient_evidence is True
    assert result.citations == ()
    assert model.called is False

    database.close()