from app.core.config import get_settings
from app.vectorstores.base import VectorStore
from app.vectorstores.milvus import MilvusVectorStore


def get_vector_store() -> VectorStore:
    settings = get_settings()
    if settings.vector_store_provider.lower() != "milvus":
        raise ValueError(f"Unsupported vector store provider: {settings.vector_store_provider}")
    return MilvusVectorStore(
        uri=settings.milvus_uri,
        token=settings.milvus_token,
        database=settings.milvus_db,
        collection_prefix=settings.milvus_collection_prefix,
    )
