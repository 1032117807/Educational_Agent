from __future__ import annotations

import numpy as np
import pytest

from ai.config import AISettings
from ai.gateways import embeddings as embeddings_module


class FakeTextEmbedding:
    calls = 0
    arguments: dict[str, object] = {}

    def __init__(self, **kwargs) -> None:
        type(self).calls += 1
        type(self).arguments = kwargs

    def embed(self, texts, *, batch_size):
        del batch_size
        return (np.array([3.0, 4.0]) for _ in texts)

    def query_embed(self, text):
        del text
        return iter([np.array([0.0, 2.0])])


def setup_function() -> None:
    embeddings_module._embedding_models.clear()
    FakeTextEmbedding.calls = 0
    FakeTextEmbedding.arguments = {}


def test_embedding_factory_uses_fastembed_without_api_credentials(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        embeddings_module, "TextEmbedding", FakeTextEmbedding
    )
    settings = AISettings(
        _env_file=None,
        api_key="",
        embedding_model="BAAI/bge-small-zh-v1.5",
        embedding_normalize=True,
    )

    result = embeddings_module.create_embedding_model(settings)

    assert isinstance(result, embeddings_module.FastEmbedEmbeddings)
    assert FakeTextEmbedding.arguments == {
        "model_name": "BAAI/bge-small-zh-v1.5",
        "providers": ["CPUExecutionProvider"],
        "lazy_load": True,
        "specific_model_path": str(
            settings.embedding_model_dir.expanduser().resolve()
        ),
    }
    assert result.embed_query("测试") == [0.0, 1.0]
    assert result.embed_documents(["甲"])[0] == pytest.approx([0.6, 0.8])


def test_embedding_factory_reuses_the_process_model(monkeypatch) -> None:
    monkeypatch.setattr(
        embeddings_module, "TextEmbedding", FakeTextEmbedding
    )
    settings = AISettings(_env_file=None)

    first = embeddings_module.create_embedding_model(settings)
    second = embeddings_module.create_embedding_model(settings)

    assert first is second
    assert FakeTextEmbedding.calls == 1
