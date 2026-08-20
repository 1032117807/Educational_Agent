from types import SimpleNamespace

from app.models import DocumentChunk
from server.pgvector_store import PgVectorStore
from server.rag_retriever import TenantPgVectorRetriever


def test_pgvector_rejects_wrong_embedding_dimension() -> None:
    store = PgVectorStore(session=None, dimensions=3)
    try:
        store.search(tenant_id="tenant", embedding_version="v1", query_embedding=[1.0, 2.0], limit=1)
    except ValueError as exc:
        assert "expected 3" in str(exc)
    else:
        raise AssertionError("wrong dimensions must fail before database access")


def test_pgvector_accepts_scope_filters_without_querying_database_on_bad_dimensions() -> None:
    store = PgVectorStore(session=None, dimensions=3)
    try:
        store.search(
            tenant_id="tenant", embedding_version="v1", query_embedding=[1.0, 2.0],
            limit=1, course_id=7, resource_ids=[11, 12],
        )
    except ValueError as exc:
        assert "expected 3" in str(exc)
    else:
        raise AssertionError("wrong dimensions must fail before database access")


def test_saas_retriever_rrf_and_rerank_publish_explainable_ranks() -> None:
    def chunk(chunk_id: int) -> DocumentChunk:
        return DocumentChunk(
            id=chunk_id, tenant_id="tenant-a", document_index_id=1, resource_id=1,
            course_id=None, chunk_number=chunk_id, content=f"content {chunk_id}",
            content_sha256=str(chunk_id) * 64, section_title="section", location_label=f"line {chunk_id}",
            metadata_json='{"source_name":"course.md","retrieval_text":"retrieval text"}',
        )

    class FakeSession:
        def execute(self, _statement, _params):
            return [SimpleNamespace(id=2)]

        def scalars(self, _statement):
            return [chunk(1), chunk(2)]

    class FakeEmbeddings:
        def embed_query(self, _query):
            return [0.1, 0.2]

    class FakeVectors:
        def search(self, **_kwargs):
            return [SimpleNamespace(chunk_id=1, distance=0.1), SimpleNamespace(chunk_id=2, distance=0.2)]

    class FakeReranker:
        def rerank(self, _query, documents, *, limit):
            assert len(documents) == limit == 2
            return [0.1, 0.9]

    retriever = TenantPgVectorRetriever(
        session=FakeSession(), embeddings=FakeEmbeddings(), embedding_version="v1", dimensions=2,
        reranker=FakeReranker(), rerank_candidate_limit=2,
    )
    retriever.vectors = FakeVectors()

    hits = retriever.retrieve("matrix", tenant_id="tenant-a", limit=2)

    assert [item.chunk_id for item in hits] == [1, 2]
    assert [item.final_rank for item in hits] == [1, 2]
    assert [item.retrieval_stage for item in hits] == ["rerank", "rerank"]
    assert hits[0].rerank_score == 0.9


def test_saas_retrieval_flags_disable_fts_and_query_rewrite() -> None:
    class FakeSession:
        def execute(self, *_args, **_kwargs):
            raise AssertionError("FTS must not run when hybrid retrieval is disabled")

        def scalars(self, _statement):
            return []

    class FakeEmbeddings:
        def __init__(self):
            self.query = ""

        def embed_query(self, query):
            self.query = query
            return [0.1, 0.2]

    class FakeVectors:
        def search(self, **_kwargs):
            return []

    embeddings = FakeEmbeddings()
    retriever = TenantPgVectorRetriever(
        session=FakeSession(), embeddings=embeddings, embedding_version="v1", dimensions=2,
        query_rewrite_enabled=False, hybrid_retrieval_enabled=False,
    )
    retriever.vectors = FakeVectors()

    assert retriever.retrieve("matrix   review", tenant_id="tenant-a") == []
    assert embeddings.query == "matrix   review"
