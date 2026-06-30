from app.core.config import get_settings
from app.knowledge.embedding.base import EmbeddingService
from app.knowledge.embedding.mock import MockEmbeddingService
from app.knowledge.embedding.openai import OpenAIEmbeddingService


def get_embedding_service() -> EmbeddingService:
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
    return MockEmbeddingService(dimension=settings.embedding_dimension)
