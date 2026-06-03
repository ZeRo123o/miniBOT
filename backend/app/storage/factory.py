from functools import lru_cache

from app.core.config import get_settings
from app.storage.base import StorageService
from app.storage.minio import MinioStorageService


@lru_cache
def get_storage() -> StorageService:
    settings = get_settings()
    provider = settings.storage_provider.lower()
    if provider != "minio":
        raise ValueError(f"Unsupported storage provider: {settings.storage_provider}")
    return MinioStorageService(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.storage_bucket,
        secure=settings.minio_secure,
    )
