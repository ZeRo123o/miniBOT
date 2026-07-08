from app.core.config import get_settings
from app.knowledge.rerank.base import RerankService
from app.knowledge.rerank.http import DashScopeCompatibleRerankService, DashScopeRerankService, OpenAIRerankService
from app.llm.providers.cache import model_cache


def get_rerank_service(*, model_name: str | None = None) -> RerankService:
    if model_name and ":" in model_name:
        return _get_rerank_service_from_model_spec(model_name)

    settings = get_settings()
    provider = (settings.rerank_provider or "openai").strip().lower()
    resolved_model_name = (model_name or settings.rerank_model_name or "").strip()
    api_key = settings.rerank_api_key or settings.openai_api_key
    base_url = settings.rerank_base_url or f"{settings.openai_base_url.rstrip('/')}/rerank"
    kwargs = {
        "model_name": resolved_model_name,
        "api_key": api_key,
        "base_url": base_url,
        "timeout_seconds": settings.rerank_timeout_seconds,
        "batch_size": settings.rerank_batch_size,
        "max_length": settings.rerank_max_length,
        "normalize_scores": settings.rerank_normalize_scores,
    }
    if provider == "dashscope":
        return DashScopeRerankService(**kwargs)
    if provider in {"dashscope-compatible", "dashscope_compatible"}:
        return DashScopeCompatibleRerankService(**kwargs)
    if provider in {"openai", "openai-compatible"}:
        return OpenAIRerankService(**kwargs)
    raise ValueError(f"Unsupported rerank provider: {settings.rerank_provider}")


def _get_rerank_service_from_model_spec(model_spec: str) -> RerankService:
    settings = get_settings()
    info = model_cache.get_model_info(model_spec)
    if info is None:
        raise ValueError(f"Unknown rerank model spec: {model_spec}")
    if info.model_type != "rerank":
        raise ValueError(f"Model spec {model_spec} is type={info.model_type}, not rerank.")

    kwargs = {
        "model_name": info.model_id,
        "api_key": info.api_key,
        "base_url": info.base_url,
        "timeout_seconds": settings.rerank_timeout_seconds,
        "batch_size": settings.rerank_batch_size,
        "max_length": settings.rerank_max_length,
        "normalize_scores": settings.rerank_normalize_scores,
        "headers": info.headers,
    }
    protocol = _rerank_protocol(info.extra)
    if protocol == "dashscope":
        return DashScopeRerankService(**kwargs)
    if protocol == "dashscope_compatible":
        return DashScopeCompatibleRerankService(**kwargs)
    return OpenAIRerankService(**kwargs)


def _rerank_protocol(extra: dict) -> str:
    protocol = str(extra.get("rerank_protocol") or extra.get("protocol") or "openai").strip().lower()
    protocol = protocol.replace("-", "_")
    if protocol in {"dashscope", "dashscope_native"}:
        return "dashscope"
    if protocol in {"dashscope_compatible", "dashscope_openai"}:
        return "dashscope_compatible"
    return "openai"
