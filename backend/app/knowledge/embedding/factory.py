from app.core.config import get_settings
from app.knowledge.embedding.base import EmbeddingService
from app.knowledge.embedding.openai import OpenAIEmbeddingService
from app.llm.providers.cache import model_cache


def get_embedding_service(model_spec: str | None = None) -> EmbeddingService:
    if model_spec:
        info = model_cache.get_model_info(model_spec)
        if info is None or info.model_type != "embedding":
            raise ValueError(f"Embedding model is unavailable: {model_spec}")
        return OpenAIEmbeddingService(
            model_name=info.model_id,
            api_key=info.api_key,
            base_url=info.base_url,
            dimension=info.dimension or get_settings().embedding_dimension,
            batch_size=info.batch_size,
            provider_id=info.provider_id,
            request_headers=info.headers,
        )

    settings = get_settings()
    provider = settings.embedding_provider.lower()
    if provider in {"openai", "openai-compatible"}:
        return OpenAIEmbeddingService(
            model_name=settings.embedding_model_name,
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            dimension=settings.embedding_dimension,
            batch_size=settings.embedding_batch_size,
        )
    raise ValueError(
        f"Unsupported embedding provider: {settings.embedding_provider}. "
        "Please configure MINIBOT_EMBEDDING_PROVIDER=openai or openai-compatible."
    )
