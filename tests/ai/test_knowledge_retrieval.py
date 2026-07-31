from __future__ import annotations

from langchain_core.documents import Document

from ai.retrieval import (
    KnowledgePointHybridRetriever,
    KnowledgePointIndex,
    KnowledgePointVectorIndex,
    SQLiteKnowledgePointIndex,
)
from app.database import Database
from app.models import Course, KnowledgePoint


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[1.0, 0.0] for _ in texts]

    def embed_query(self, text):
        return [1.0, 0.0]


class FakeVectorStore:
    def __init__(self):
        self.documents = {}
        self.search_results = []

    def add_documents(self, *, documents, ids):
        for vector_id, document in zip(ids, documents, strict=True):
            self.documents[vector_id] = document

    def delete(self, *, ids):
        for vector_id in ids:
            self.documents.pop(vector_id, None)

    def similarity_search_with_score(self, **_kwargs):
        return self.search_results


def prepare_points(database: Database) -> tuple[int, int, int]:
    with database.session() as session:
        course = Course(name="数学")
        session.add(course)
        session.flush()
        first = KnowledgePoint(
            course_id=course.id,
            name="函数极限",
            category="定义",
            definition="描述函数值的趋近趋势",
            importance=5,
            source="ai",
        )
        second = KnowledgePoint(
            course_id=course.id,
            name="连续性",
            category="概念",
            definition="函数在某点连续",
            source="ai",
        )
        session.add_all([first, second])
        session.flush()
        return course.id, first.id, second.id


def test_knowledge_point_is_written_to_fts_and_vector_store(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'index.db').as_posix()}")
    database.create_schema()
    course_id, first_id, _ = prepare_points(database)
    fake_store = FakeVectorStore()
    vectors = KnowledgePointVectorIndex(
        database=database,
        embeddings=FakeEmbeddings(),
        persist_directory=tmp_path / "vectors",
        embedding_model="test-embedding",
        vector_store=fake_store,
    )
    keywords = SQLiteKnowledgePointIndex(database)
    index = KnowledgePointIndex(
        database=database, keywords=keywords, vectors=vectors
    )

    vector_id = index.upsert(first_id)

    assert vector_id == f"knowledge-point-{first_id}"
    assert "函数极限" in fake_store.documents[vector_id].page_content
    assert keywords.search("函数极限", course_id=course_id)[0].knowledge_point_id == first_id
    with database.session() as session:
        point = session.get(KnowledgePoint, first_id)
        assert point.vector_id == vector_id
        assert point.embedding_model == "test-embedding"
    database.close()


def test_knowledge_rrf_merges_keyword_and_semantic_results(tmp_path) -> None:
    database = Database(f"sqlite:///{(tmp_path / 'hybrid.db').as_posix()}")
    database.create_schema()
    course_id, first_id, second_id = prepare_points(database)
    fake_store = FakeVectorStore()
    vectors = KnowledgePointVectorIndex(
        database=database,
        embeddings=FakeEmbeddings(),
        persist_directory=tmp_path / "vectors",
        embedding_model="test-embedding",
        vector_store=fake_store,
    )
    keywords = SQLiteKnowledgePointIndex(database)
    index = KnowledgePointIndex(
        database=database, keywords=keywords, vectors=vectors
    )
    index.rebuild()
    fake_store.search_results = [(
        Document(
            page_content="连续性",
            metadata={"knowledge_point_id": second_id, "course_id": course_id},
        ),
        0.1,
    )]
    retriever = KnowledgePointHybridRetriever(
        database=database,
        keyword_index=keywords,
        vector_index=vectors,
    )

    hits = retriever.retrieve("函数极限", course_id=course_id)

    assert {hit.knowledge_point_id for hit in hits} == {first_id, second_id}
    keyword_hit = next(hit for hit in hits if hit.knowledge_point_id == first_id)
    semantic_hit = next(hit for hit in hits if hit.knowledge_point_id == second_id)
    assert keyword_hit.keyword_rank == 1
    assert keyword_hit.semantic_rank is None
    assert semantic_hit.semantic_rank == 1
    assert semantic_hit.keyword_rank == 2
    assert semantic_hit.rrf_score > keyword_hit.rrf_score
    database.close()
