import asyncio
from io import BytesIO

from minio import Minio
from minio.error import S3Error
from urllib3.exceptions import HTTPError

from app.storage.base import StorageService, StorageUnavailableError


class MinioStorageService(StorageService):
    def __init__(
        self,
        *,
        endpoint: str,
        access_key: str,
        secret_key: str,
        bucket: str,
        secure: bool = False,
    ):
        self.bucket = bucket
        self.client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
        )

    async def put_bytes(self, object_key: str, data: bytes, content_type: str | None = None) -> str:
        await asyncio.to_thread(self._put_bytes_sync, object_key, data, content_type)
        return object_key

    async def get_bytes(self, object_key: str) -> bytes:
        return await asyncio.to_thread(self._get_bytes_sync, object_key)

    async def delete_object(self, object_key: str) -> None:
        if object_key:
            await asyncio.to_thread(self.client.remove_object, self.bucket, object_key)

    async def delete_prefix(self, prefix: str) -> None:
        await asyncio.to_thread(self._delete_prefix_sync, prefix)

    def _put_bytes_sync(self, object_key: str, data: bytes, content_type: str | None) -> None:
        try:
            self._ensure_bucket()
            self.client.put_object(
                self.bucket,
                object_key,
                BytesIO(data),
                length=len(data),
                content_type=content_type or "application/octet-stream",
            )
        except (HTTPError, OSError) as error:
            raise StorageUnavailableError("Object storage is unavailable.") from error

    def _get_bytes_sync(self, object_key: str) -> bytes:
        try:
            response = self.client.get_object(self.bucket, object_key)
        except (HTTPError, OSError) as error:
            raise StorageUnavailableError("Object storage is unavailable.") from error
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def _delete_prefix_sync(self, prefix: str) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                return
            for item in self.client.list_objects(self.bucket, prefix=prefix, recursive=True):
                self.client.remove_object(self.bucket, item.object_name)
        except (HTTPError, OSError) as error:
            raise StorageUnavailableError("Object storage is unavailable.") from error

    def _ensure_bucket(self) -> None:
        try:
            if not self.client.bucket_exists(self.bucket):
                self.client.make_bucket(self.bucket)
        except S3Error:
            raise
        except (HTTPError, OSError) as error:
            raise StorageUnavailableError("Object storage is unavailable.") from error
