import pytest

from ai.config import AISettings


def test_pgvector_schema_rejects_unsupported_embedding_dimensions() -> None:
    with pytest.raises(ValueError, match="embedding_dimensions"):
        AISettings(embedding_dimensions=768)


def test_pgvector_schema_accepts_512_dimensions() -> None:
    assert AISettings(embedding_dimensions=512).embedding_dimensions == 512


def test_local_embedding_does_not_require_an_api_key() -> None:
    settings = AISettings(enabled=False, api_key="", embedding_dimensions=512)
    assert settings.embedding_model == "BAAI/bge-small-zh-v1.5"


def test_enabled_chat_requires_server_side_api_key() -> None:
    with pytest.raises(ValueError, match="LEARNING_AI_API_KEY"):
        AISettings(enabled=True, api_key="", embedding_dimensions=512)


def test_openai_compatible_chat_requires_base_url() -> None:
    with pytest.raises(ValueError, match="LEARNING_AI_BASE_URL"):
        AISettings(
            enabled=True,
            provider="openai_compatible",
            api_key="server-only-key",
            base_url="",
            embedding_dimensions=512,
        )
