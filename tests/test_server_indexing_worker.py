from pathlib import Path

from server.indexing_worker import index_resource_from_object_store


class FakeStorage:
    def download_to(self, *, key: str, destination: Path) -> None:
        assert key == "tenant-1/resources/r1/source.txt"
        destination.write_text("source", encoding="utf-8")


def test_index_worker_rejects_unknown_resource() -> None:
    class EmptySession:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def scalar(self, statement): return None

    try:
        index_resource_from_object_store(
            payload={"resource_id": 1, "tenant_id": "tenant-1"},
            session_factory=EmptySession,
            storage=FakeStorage(),
                pipeline_factory=lambda *_: None,
        )
    except ValueError as exc:
        assert "resource not found" in str(exc)
    else:
        raise AssertionError("unknown resource must be rejected")
