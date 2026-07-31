from __future__ import annotations

from pathlib import Path
from threading import RLock

import numpy as np
from langchain_core.embeddings import Embeddings

from ai.config import AISettings


# Injectable for tests; imported lazily so application startup stays lightweight.
TextEmbedding = None

_embedding_models: dict[
    tuple[str, bool, int, str, bool, type],
    Embeddings,
] = {}
_embedding_models_lock = RLock()


class FastEmbedEmbeddings(Embeddings):
    """LangChain adapter for FastEmbed's PyTorch-free ONNX runtime."""

    def __init__(
        self,
        *,
        model_name: str,
        normalize_embeddings: bool,
        batch_size: int,
        model_dir: Path,
        local_files_only: bool,
        embedding_class: type | None = None,
    ) -> None:
        if embedding_class is None:
            from fastembed import TextEmbedding as embedding_class

        self.model_name = model_name
        self.normalize_embeddings = normalize_embeddings
        self.batch_size = batch_size
        resolved_model_dir = model_dir.expanduser().resolve()
        if local_files_only and not resolved_model_dir.is_dir():
            raise RuntimeError(
                f"本地 ONNX 模型目录不存在：{resolved_model_dir}"
            )
        arguments: dict[str, object] = {
            "model_name": model_name,
            "providers": ["CPUExecutionProvider"],
            "lazy_load": True,
        }
        if resolved_model_dir.is_dir():
            arguments["specific_model_path"] = str(resolved_model_dir)
        else:
            arguments["cache_dir"] = str(resolved_model_dir.parent)
        self.model = embedding_class(**arguments)

    def _convert(self, values: object) -> list[list[float]]:
        result: list[list[float]] = []
        for value in values:
            vector = np.asarray(value, dtype=np.float32)
            if self.normalize_embeddings:
                norm = float(np.linalg.norm(vector))
                if norm:
                    vector = vector / norm
            result.append(vector.tolist())
        return result

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return self._convert(
            self.model.embed(texts, batch_size=self.batch_size)
        )

    def embed_query(self, text: str) -> list[float]:
        vectors = self._convert(self.model.query_embed(text))
        if not vectors:
            raise RuntimeError("ONNX 编码模型没有返回查询向量")
        return vectors[0]


def create_embedding_model(settings: AISettings) -> Embeddings:
    """Create and reuse the local ONNX BGE embedding model."""

    embedding_class = TextEmbedding
    if embedding_class is None:
        try:
            from fastembed import TextEmbedding as embedding_class
        except ImportError as exc:
            raise RuntimeError(
                "本地 ONNX 编码器未安装，请执行：pip install fastembed"
            ) from exc

    key = (
        settings.embedding_model,
        settings.embedding_normalize,
        settings.embedding_batch_size,
        str(settings.embedding_model_dir),
        settings.embedding_local_files_only,
        embedding_class,
    )

    with _embedding_models_lock:
        cached = _embedding_models.get(key)
        if cached is not None:
            return cached

        model = FastEmbedEmbeddings(
            model_name=settings.embedding_model,
            normalize_embeddings=settings.embedding_normalize,
            batch_size=settings.embedding_batch_size,
            model_dir=settings.embedding_model_dir,
            local_files_only=settings.embedding_local_files_only,
            embedding_class=embedding_class,
        )
        _embedding_models[key] = model
        return model
