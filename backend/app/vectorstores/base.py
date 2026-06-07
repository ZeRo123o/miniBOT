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

    @abstractmethod
    async def search_chunks(
        self,
        *,
        knowledge_base_id: int,
        query_text: str,
        query_embedding: list[float],
        search_mode: str,
        final_top_k: int,
        recall_top_k: int,
        similarity_threshold: float,
        bm25_top_k: int,
        vector_weight: float,
        bm25_weight: float,
        bm25_drop_ratio_search: float,
        include_distances: bool,
        document_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """Search chunk content with dense vectors, BM25, or both."""
