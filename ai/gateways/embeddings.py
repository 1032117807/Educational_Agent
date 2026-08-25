from __future__ import annotations

from pathlib import Path
from threading import RLock
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

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
        model_file = resolved_model_dir / "model_optimized.onnx"
        if local_files_only and not model_file.is_file():
            raise RuntimeError(
                f"本地 ONNX 模型目录不存在：{resolved_model_dir}"
            )
        arguments: dict[str, object] = {
            "model_name": model_name,
            "providers": ["CPUExecutionProvider"],
            "lazy_load": True,
        }
        if model_file.is_file():
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


class OpenAICompatibleEmbeddings(Embeddings):
    """Embedding adapter for SiliconFlow and other OpenAI-compatible APIs."""

    def __init__(self, *, api_key: str, base_url: str, model: str, normalize: bool, batch_size: int, timeout: float) -> None:
        self.api_key, self.base_url, self.model = api_key, base_url.rstrip("/"), model
        self.normalize, self.batch_size, self.timeout = normalize, batch_size, timeout

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        request = Request(
            f"{self.base_url}/embeddings",
            data=json.dumps({"model": self.model, "input": texts}, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"embedding API returned HTTP {exc.code}: {detail}") from exc
        except URLError as exc:
            raise RuntimeError(f"embedding API is unavailable: {exc.reason}") from exc
        rows = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(rows, list):
            raise ValueError("embedding API response has no data list")
        vectors = [row.get("embedding") for row in sorted(rows, key=lambda item: item.get("index", 0)) if isinstance(row, dict)]
        if len(vectors) != len(texts) or any(not isinstance(vector, list) for vector in vectors):
            raise ValueError("embedding API returned an unexpected vector count")
        result = [[float(value) for value in vector] for vector in vectors]
        if self.normalize:
            for vector in result:
                norm = float(np.linalg.norm(vector))
                if norm:
                    for index, value in enumerate(vector):
                        vector[index] = value / norm
        return result

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [vector for start in range(0, len(texts), self.batch_size) for vector in self._embed(texts[start:start + self.batch_size])]

    def embed_query(self, text: str) -> list[float]:
        vectors = self._embed([text])
        if not vectors:
            raise RuntimeError("embedding API returned no query vector")
        return vectors[0]


def create_embedding_model(settings: AISettings) -> Embeddings:
    """Create and reuse the configured local or remote embedding model."""
    if settings.embedding_provider != "local":
        if not settings.embedding_api_key.strip():
            raise ValueError("LEARNING_AI_EMBEDDING_API_KEY is required for remote embeddings")
        base_url = settings.embedding_base_url or "https://api.siliconflow.cn/v1"
        return OpenAICompatibleEmbeddings(
            api_key=settings.embedding_api_key,
            base_url=base_url,
            model=settings.embedding_model,
            normalize=settings.embedding_normalize,
            batch_size=settings.embedding_batch_size,
            timeout=settings.request_timeout_seconds,
        )

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
