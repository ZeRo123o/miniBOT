from typing import Any

import httpx

from app.knowledge.embedding.base import EmbeddingService


class OpenAIEmbeddingService(EmbeddingService):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        dimension: int,
        batch_size: int = 10,
        request_headers: dict[str, str] | None = None,
    ):
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.dimension = dimension
        self.batch_size = max(int(batch_size), 1)
        self.request_headers = request_headers or {}

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        if not self.api_key:
            raise ValueError("MINIBOT_OPENAI_API_KEY is required for OpenAI-compatible embeddings.")

        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            batch = texts[start : start + self.batch_size]
            embeddings.extend(await self._embed_batch(batch))

        if embeddings:
            self.dimension = len(embeddings[0])
        return embeddings

    async def _embed_batch(self, texts: list[str]) -> list[list[float]]:
        payload: dict[str, Any] = {
            "model": self.model_name,
            "input": texts,
        }
        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                self._url_with_endpoint("embeddings"),
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                    **self.request_headers,
                },
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                body = response.text[:1000]
                raise ValueError(
                    f"Embedding request failed: status={response.status_code}, body={body}"
                ) from error
            data = response.json()

        return [item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"])]

    def _url_with_endpoint(self, endpoint: str) -> str:
        normalized = endpoint.strip("/")
        if self.base_url.rstrip("/").endswith(f"/{normalized}"):
            return self.base_url
        return f"{self.base_url}/{normalized}"
