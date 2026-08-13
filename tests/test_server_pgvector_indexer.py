from server.pgvector_indexer import embedding_version_for


def test_embedding_version_changes_with_model_or_dimensions() -> None:
    assert embedding_version_for("model-a", 384) == embedding_version_for("model-a", 384)
    assert embedding_version_for("model-a", 384) != embedding_version_for("model-a", 768)
    assert embedding_version_for("model-a", 384) != embedding_version_for("model-b", 384)
