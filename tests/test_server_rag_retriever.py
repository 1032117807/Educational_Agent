from server.pgvector_store import PgVectorStore


def test_pgvector_rejects_wrong_embedding_dimension() -> None:
    store = PgVectorStore(session=None, dimensions=3)
    try:
        store.search(tenant_id="tenant", embedding_version="v1", query_embedding=[1.0, 2.0], limit=1)
    except ValueError as exc:
        assert "expected 3" in str(exc)
    else:
        raise AssertionError("wrong dimensions must fail before database access")
