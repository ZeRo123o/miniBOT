from app.core.config import get_settings
from app.knowledge.rerank.base import RerankService
from app.knowledge.rerank.http import DashScopeRerankService, OpenAIRerankService


def get_rerank_service(*, model_name: str | None = None) -> RerankService:
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
    if provider in {"openai", "openai-compatible"}:
        return OpenAIRerankService(**kwargs)
    raise ValueError(f"Unsupported rerank provider: {settings.rerank_provider}")
