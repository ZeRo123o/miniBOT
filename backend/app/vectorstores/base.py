from abc import ABC, abstractmethod
from typing import Any


class VectorStore(ABC):
    @abstractmethod
    async def upsert_chunks(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
        dimension: int,
    ) -> None:
        """Insert or replace chunk vectors for one document."""

    @abstractmethod
    async def delete_document_chunks(self, *, knowledge_base_id: int, document_id: int) -> None:
        """Delete all vector records for one document."""
