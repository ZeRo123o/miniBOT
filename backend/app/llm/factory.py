from dataclasses import dataclass

from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import get_settings
from app.llm.chat_model import MiniBotChatModel

CHAT_MODEL = "chat_model"
DEEP_RESEARCH_MODEL = "deep_research_model"


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    name: str


def _model_config(model_use: str) -> ModelConfig:
    settings = get_settings()
    if model_use == DEEP_RESEARCH_MODEL:
        return ModelConfig(
            provider=settings.deep_research_model_provider or settings.default_model_provider,
            name=settings.deep_research_model_name or settings.default_model_name or settings.default_model,
        )
    return ModelConfig(
        provider=settings.chat_model_provider or settings.default_model_provider,
        name=settings.chat_model_name or settings.default_model_name or settings.default_model,
    )


def get_model(model_use: str = CHAT_MODEL) -> BaseChatModel:
    settings = get_settings()
    model_config = _model_config(model_use)
    provider = model_config.provider.lower()

    if provider in {"openai", "openai-compatible", "compatible"}:
        provider = "openai-compatible"

    if provider != "mock" and provider != "openai-compatible":
        raise ValueError(f"Unsupported model provider: {model_config.provider}")

    return MiniBotChatModel(
        provider=provider,
        model_name=model_config.name,
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        temperature=settings.openai_temperature,
    )


def get_chat_model() -> BaseChatModel:
    return get_model(CHAT_MODEL)


def get_deep_research_model() -> BaseChatModel:
    return get_model(DEEP_RESEARCH_MODEL)
