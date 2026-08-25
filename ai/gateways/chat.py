from __future__ import annotations

from langchain_core.language_models.chat_models import BaseChatModel

from ai.config import AISettings
from ai.exceptions import AIConfigurationError
from ai.usage import UsageCollector


def normalize_openai_base_url(base_url: str) -> str:
    """Return the API root expected by OpenAI-compatible clients."""
    normalized = base_url.strip().rstrip("/")
    if not normalized.lower().endswith("/v1"):
        normalized += "/v1"
    return normalized


def create_chat_model(settings: AISettings) -> BaseChatModel:
    if not settings.api_key.strip():
        raise AIConfigurationError("尚未配置 Chat API Key")

    # langchain-openai may import optional tokenizer integrations which load
    # PyTorch. Keep that native dependency out of desktop application startup.
    from langchain_openai import ChatOpenAI

    arguments: dict[str, object] = {
        "model": settings.chat_model,
        "api_key": settings.api_key,
        "temperature": settings.temperature,
        "request_timeout": settings.request_timeout_seconds,
        "max_retries": settings.max_retries,
        # 挂在模型上而非逐次调用传入，这样 with_structured_output 包装后
        # 仍能拿到原始响应的 usage。
        "callbacks": [UsageCollector()],
    }

    if settings.base_url:
        arguments["base_url"] = normalize_openai_base_url(settings.base_url)

    return ChatOpenAI(**arguments)
