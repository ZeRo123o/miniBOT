from abc import ABC, abstractmethod


class StorageUnavailableError(RuntimeError):
    """Raised when the configured object storage service cannot be reached."""


class StorageService(ABC):
    @abstractmethod
    async def put_bytes(self, object_key: str, data: bytes, content_type: str | None = None) -> str:
        """Store bytes and return the object key."""

    @abstractmethod
    async def get_bytes(self, object_key: str) -> bytes:
        """Read object bytes."""

    @abstractmethod
    async def delete_object(self, object_key: str) -> None:
        """Delete one object if it exists."""

    @abstractmethod
    async def delete_prefix(self, prefix: str) -> None:
        """Delete all objects whose keys start with the prefix."""
