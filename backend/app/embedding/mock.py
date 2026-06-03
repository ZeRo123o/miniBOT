import hashlib
import math

from app.embedding.base import EmbeddingService


class MockEmbeddingService(EmbeddingService):
    model_name = "mock"

    def __init__(self, dimension: int = 384):
        self.dimension = max(int(dimension or 384), 8)

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def _embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = self._tokens(text)
        if not tokens:
            tokens = [text or ""]

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8", errors="ignore")).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]

    def _tokens(self, text: str) -> list[str]:
        return [part for part in (text or "").replace("\n", " ").split(" ") if part]
