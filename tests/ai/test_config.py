from pathlib import Path

from ai.config import AISettings

def test_ai_settings_can_be_created_without_api_key() -> None:
    settings = AISettings(
        _env_file=None,
        enabled=False,
    )

    assert settings.enabled is False
    assert settings.chunk_size == 800
    assert settings.chunk_overlap < settings.chunk_size
    assert settings.retrieval_top_k == 8
    assert settings.embedding_model == "BAAI/bge-small-zh-v1.5"
    assert settings.embedding_device == "cpu"
    assert settings.embedding_normalize is True
    assert settings.embedding_local_files_only is True


def test_ai_settings_accept_custom_vector_store_path() -> None:
    settings = AISettings(
        _env_file=None,
        vector_store_dir=Path("temporary/vector-store"),
    )

    assert settings.vector_store_dir == Path("temporary/vector-store")
