from abc import ABC, abstractmethod


class StorageService(ABC):
    @abstractmethod
    async def put_bytes(self, object_key: str, data: bytes, content_type: str | None = None) -> str:
        """Store bytes and return the object key."""

    @abstractmethod
    async def get_bytes(self, object_key: str) -> bytes:
        """Read object bytes."""
