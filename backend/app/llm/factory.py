from app.core.config import get_settings
from app.llm.base import ChatModel
from app.llm.providers.mock import MockChatModel
from app.llm.providers.openai_compatible import OpenAICompatibleChatModel


def get_chat_model() -> ChatModel:
    settings = get_settings()
    provider = settings.default_model_provider.lower()

    if provider == "mock":
        return MockChatModel()

    if provider in {"openai", "openai-compatible", "compatible"}:
        return OpenAICompatibleChatModel(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.default_model_name or settings.default_model,
            temperature=settings.openai_temperature,
        )

    raise ValueError(f"Unsupported model provider: {settings.default_model_provider}")
