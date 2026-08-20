from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from ai.config import AISettings

logger = logging.getLogger(__name__)


class Reranker(Protocol):
    def rerank(self, query: str, documents: list[str], *, limit: int) -> list[float]: ...


@dataclass(frozen=True, slots=True)
class OpenAICompatibleReranker:
    """Call the common `/rerank` API exposed by SiliconFlow-compatible hosts."""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float

    def rerank(self, query: str, documents: list[str], *, limit: int) -> list[float]:
        if not documents:
            return []
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_n": min(limit, len(documents)),
            "return_documents": False,
        }
        response = _post_json(f"{self.base_url.rstrip('/')}/rerank", self.api_key, payload, self.timeout_seconds)
        return _scores_from_results(response, len(documents))


@dataclass(frozen=True, slots=True)
class AliyunReranker:
    """Call DashScope text-reranking. Alibaba uses a different request shape."""

    api_key: str
    base_url: str
    model: str
    timeout_seconds: float

    def rerank(self, query: str, documents: list[str], *, limit: int) -> list[float]:
        if not documents:
            return []
        payload = {
            "model": self.model,
            "input": {"query": query, "documents": documents},
            "parameters": {"top_n": min(limit, len(documents)), "return_documents": False},
        }
        response = _post_json(self.base_url, self.api_key, payload, self.timeout_seconds)
        output = response.get("output", response)
        if not isinstance(output, dict):
            raise ValueError("Alibaba rerank response has no output object")
        return _scores_from_results(output, len(documents))


def create_reranker(settings: AISettings) -> Reranker | None:
    if not settings.rerank_enabled:
        return None
    if settings.rerank_provider in {"siliconflow", "openai_compatible"}:
        base_url = settings.rerank_base_url or "https://api.siliconflow.cn/v1"
        return OpenAICompatibleReranker(settings.rerank_api_key, base_url, settings.rerank_model, settings.request_timeout_seconds)
    if settings.rerank_provider == "aliyun":
        base_url = settings.rerank_base_url or "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-reranking/text-reranking"
        return AliyunReranker(settings.rerank_api_key, base_url, settings.rerank_model, settings.request_timeout_seconds)
    raise ValueError(f"unsupported rerank provider: {settings.rerank_provider}")


def _post_json(url: str, api_key: str, payload: dict[str, object], timeout_seconds: float) -> dict[str, object]:
    request = Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            decoded = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"rerank API returned HTTP {exc.code}: {body}") from exc
    except URLError as exc:
        raise RuntimeError(f"rerank API is unavailable: {exc.reason}") from exc
    if not isinstance(decoded, dict):
        raise ValueError("rerank API returned a non-object JSON response")
    return decoded


def _scores_from_results(payload: dict[str, object], expected_count: int) -> list[float]:
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("rerank response has no results list")
    scores = [float("-inf")] * expected_count
    for result in results:
        if not isinstance(result, dict):
            continue
        index = result.get("index")
        score = result.get("relevance_score", result.get("score"))
        if isinstance(index, int) and 0 <= index < expected_count and isinstance(score, (int, float)):
            scores[index] = float(score)
    if all(score == float("-inf") for score in scores):
        raise ValueError("rerank response contains no usable result scores")
    return scores
