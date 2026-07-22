import logging
import re
from typing import Any

import httpx

from app.knowledge.embedding.base import EmbeddingService

logger = logging.getLogger(__name__)

KNOWN_EMBEDDING_BATCH_LIMITS: dict[tuple[str | None, str], int] = {
    ("alibaba", "text-embedding-v4"): 10,
    ("alibaba-cn", "text-embedding-v4"): 10,
}
KNOWN_EMBEDDING_BASE_URL_LIMITS: tuple[tuple[str, str, int], ...] = (
    ("dashscope.aliyuncs.com", "text-embedding-v4", 10),
    ("dashscope-intl.aliyuncs.com", "text-embedding-v4", 10),
)


class OpenAIEmbeddingService(EmbeddingService):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        dimension: int,
        batch_size: int = 10,
        provider_id: str | None = None,
        request_headers: dict[str, str] | None = None,
    ):
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.dimension = dimension
        self.provider_id = provider_id
        self.configured_batch_size = max(int(batch_size), 1)
        self.batch_size = resolve_embedding_batch_size(
            provider_id=provider_id,
            model_name=model_name,
            base_url=base_url,
            configured_batch_size=self.configured_batch_size,
        )
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
        if not texts:
            return []
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
                retry_limit = _batch_limit_from_error(body)
                if response.status_code == 400 and retry_limit and len(texts) > retry_limit:
                    logger.warning(
                        "Embedding batch rejected; retrying with provider limit: "
                        "model=%s, base_url=%s, input_count=%s, retry_batch_size=%s",
                        self.model_name,
                        self.base_url,
                        len(texts),
                        retry_limit,
                    )
                    self.batch_size = min(self.batch_size, retry_limit)
                    return await self._embed_in_batches(texts, retry_limit)
                if response.status_code == 400:
                    logger.warning(
                        "Embedding request returned 400 Bad Request: "
                        "model=%s, base_url=%s, input_count=%s, input_lengths=%s, body=%s",
                        self.model_name,
                        self.base_url,
                        len(texts),
                        [len(item) for item in texts],
                        body,
                    )
                raise ValueError(
                    f"Embedding request failed: status={response.status_code}, body={body}"
                ) from error
            data = response.json()

        return [item["embedding"] for item in sorted(data["data"], key=lambda item: item["index"])]

    async def _embed_in_batches(self, texts: list[str], batch_size: int) -> list[list[float]]:
        embeddings: list[list[float]] = []
        safe_batch_size = max(int(batch_size), 1)
        for start in range(0, len(texts), safe_batch_size):
            embeddings.extend(await self._embed_batch(texts[start : start + safe_batch_size]))
        return embeddings

    def _url_with_endpoint(self, endpoint: str) -> str:
        normalized = endpoint.strip("/")
        if self.base_url.rstrip("/").endswith(f"/{normalized}"):
            return self.base_url
        return f"{self.base_url}/{normalized}"


def resolve_embedding_batch_size(
    *,
    provider_id: str | None,
    model_name: str,
    base_url: str,
    configured_batch_size: int,
) -> int:
    """Clamp configured batch size to known provider/model limits."""
    configured = max(int(configured_batch_size), 1)
    normalized_model = model_name.strip()
    limit = KNOWN_EMBEDDING_BATCH_LIMITS.get((provider_id, normalized_model))
    normalized_base_url = base_url.lower()
    for host_fragment, limited_model, host_limit in KNOWN_EMBEDDING_BASE_URL_LIMITS:
        if host_fragment in normalized_base_url and limited_model == normalized_model:
            limit = host_limit if limit is None else min(limit, host_limit)
    return min(configured, limit) if limit else configured


def _batch_limit_from_error(body: str) -> int | None:
    match = re.search(r"not be larger than\s+(\d+)", body, flags=re.IGNORECASE)
    if not match:
        return None
    try:
        return max(int(match.group(1)), 1)
    except ValueError:
        return None
