from abc import ABC, abstractmethod


class EmbeddingService(ABC):
    dimension: int
    model_name: str

    @abstractmethod
    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one embedding vector for each input text."""
