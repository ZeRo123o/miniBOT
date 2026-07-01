from abc import ABC, abstractmethod


class RerankService(ABC):
    """Common interface for reranking retrieved knowledge chunks."""

    @abstractmethod
    async def rerank(self, *, query: str, documents: list[str]) -> list[float]:
        """Return one relevance score for each document."""
