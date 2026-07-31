from __future__ import annotations

import json

from ai.retrieval import SQLiteKeywordIndex, tokenize_for_search
from app.database import Database
from app.models import (
    DocumentChunk,
    DocumentIndex,
    ResourceFile,
)


def prepare_chunks(database: Database) -> int:
    with database.session() as session:
        resource = ResourceFile(
            name="高等数学.pdf",
            original_name="高等数学.pdf",
            source_path="",
            relative_path="高等数学.pdf",
            sha256="a" * 64,
            size=100,
            course_id=None,
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
            chunk_count=2,
        )
        session.add(index)
        session.flush()

        contents = [
            "函数极限描述函数在自变量变化时的趋势。",
            "导数表示函数在某一点的瞬时变化率。",
        ]

        for number, content in enumerate(contents):
            session.add(
                DocumentChunk(
                    document_index_id=index.id,
                    resource_id=resource.id,
                    chunk_number=number,
                    content=content,
                    content_sha256=str(number + 1) * 64,
                    location_label=f"第 {number + 1} 页",
                    metadata_json=json.dumps({
                        "retrieval_text": content,
                        "source_name": "高等数学.pdf",
                    }, ensure_ascii=False),
                )
            )

        return index.id


def test_chinese_text_is_tokenized() -> None:
    tokens = tokenize_for_search("函数极限与连续性")

    assert "函数" in tokens
    assert "极限" in tokens


def test_keyword_search_finds_exact_concept(tmp_path) -> None:
    database = Database(
        f"sqlite:///{(tmp_path / 'fts.db').as_posix()}"
    )
    database.create_schema()
    index_id = prepare_chunks(database)

    keywords = SQLiteKeywordIndex(database)
    assert keywords.rebuild_document(index_id) == 2

    hits = keywords.search("函数极限")

    assert hits
    assert hits[0].rank == 1

    database.close()