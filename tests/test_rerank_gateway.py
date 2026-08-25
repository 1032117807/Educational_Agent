from ai.config import AISettings
from ai.gateways.rerank import AliyunReranker, OpenAICompatibleReranker, _scores_from_results, create_reranker


def test_rerank_is_disabled_by_default(monkeypatch) -> None:
    # Do not let a developer's local .env turn a default-value test into an
    # integration test. Production settings still load .env normally.
    monkeypatch.delenv("LEARNING_AI_ENABLED", raising=False)
    monkeypatch.delenv("LEARNING_AI_RERANK_ENABLED", raising=False)
    assert create_reranker(AISettings(_env_file=None)) is None


def test_siliconflow_uses_openai_compatible_rerank_endpoint() -> None:
    reranker = create_reranker(AISettings(rerank_enabled=True, rerank_api_key="key"))
    assert isinstance(reranker, OpenAICompatibleReranker)
    assert reranker.base_url == "https://api.siliconflow.cn/v1"


def test_aliyun_uses_dashscope_rerank_adapter() -> None:
    reranker = create_reranker(AISettings(rerank_enabled=True, rerank_provider="aliyun", rerank_api_key="key"))
    assert isinstance(reranker, AliyunReranker)


def test_rerank_scores_keep_api_indexes() -> None:
    assert _scores_from_results({"results": [{"index": 1, "relevance_score": 0.9}, {"index": 0, "relevance_score": 0.2}]}, 2) == [0.2, 0.9]
