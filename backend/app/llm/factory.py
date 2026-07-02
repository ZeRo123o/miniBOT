from langchain_core.language_models.chat_models import BaseChatModel

from app.core.config import get_settings
from app.llm.chat_model import MiniBotChatModel
from app.llm.providers.cache import ModelInfo, model_cache

CHAT_MODEL = "chat_model"
DEEP_RESEARCH_MODEL = "deep_research_model"


def _runtime_provider(provider_type: str) -> str:
    if provider_type == "mock":
        return "mock"
    if provider_type in {"openai", "openai-compatible", "openrouter"}:
        return "openai-compatible"
    raise ValueError(f"Unsupported model provider type: {provider_type}")


def _model_info_for_use(model_use: str) -> ModelInfo:
    configured_spec = model_cache.get_model_use_spec(model_use)
    if not configured_spec:
        raise ValueError(f"模型用途 {model_use} 未配置，请在模型配置页设置运行用途并刷新缓存。")

    info = model_cache.get_model_info(configured_spec)
    if info is None:
        raise ValueError(f"模型 {configured_spec} 不可用，请在模型配置页启用该模型并刷新缓存。")
    if info.model_type != "chat":
        raise ValueError(f"Model {configured_spec} is not a chat model")
    return info


def _chat_model_from_info(info: ModelInfo) -> MiniBotChatModel:
    settings = get_settings()
    return MiniBotChatModel(
        provider=info.extra.get("runtime_provider") or _runtime_provider(info.provider_type),
        model_name=info.model_id,
        api_key=info.api_key,
        base_url=info.base_url,
        temperature=settings.openai_temperature,
        timeout_seconds=settings.openai_timeout_seconds,
        request_headers=info.headers,
    )


def get_model(model_use: str = CHAT_MODEL) -> BaseChatModel:
    return _chat_model_from_info(_model_info_for_use(model_use))


def get_model_by_spec(model_spec: str) -> BaseChatModel:
    info = model_cache.get_model_info(model_spec)
    if info is None:
        raise ValueError(f"Unknown model spec: {model_spec}")
    if info.model_type != "chat":
        raise ValueError(f"Model {model_spec} is not a chat model")
    return _chat_model_from_info(info)


def get_chat_model() -> BaseChatModel:
    return get_model(CHAT_MODEL)


def get_deep_research_model() -> BaseChatModel:
    return get_model(DEEP_RESEARCH_MODEL)
