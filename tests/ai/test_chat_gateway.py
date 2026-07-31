from unittest.mock import patch

from ai.config import AISettings
from ai.gateways.chat import create_chat_model, normalize_openai_base_url


def test_normalize_openai_base_url_adds_v1_to_host_root():
    assert (
        normalize_openai_base_url(" https://api.example.test/ ")
        == "https://api.example.test/v1"
    )


def test_normalize_openai_base_url_preserves_existing_v1():
    assert (
        normalize_openai_base_url("https://api.example.test/v1/")
        == "https://api.example.test/v1"
    )


def test_create_chat_model_uses_normalized_base_url():
    settings = AISettings(
        api_key="test-key",
        base_url="https://api.example.test",
        chat_model="test-model",
    )

    with patch("langchain_openai.ChatOpenAI") as chat_openai:
        model = create_chat_model(settings)

    assert model is chat_openai.return_value
    assert chat_openai.call_args.kwargs["base_url"] == (
        "https://api.example.test/v1"
    )
