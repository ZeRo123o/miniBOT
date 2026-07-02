import math
from abc import abstractmethod
from typing import Any

import httpx

from app.knowledge.rerank.base import RerankService


class HTTPRerankService(RerankService):
    """Batching HTTP reranker with OpenAI-like and DashScope-compatible subclasses."""

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        base_url: str,
        timeout_seconds: float,
        batch_size: int,
        max_length: int,
        normalize_scores: bool,
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = max(float(timeout_seconds), 1.0)
        self.batch_size = max(int(batch_size), 1)
        self.max_length = max(int(max_length), 1)
        self.normalize_scores = bool(normalize_scores)

    async def rerank(self, *, query: str, documents: list[str]) -> list[float]:
        if not query.strip() or not documents:
            return []
        if not self.model_name:
            raise ValueError("Rerank model name is required.")
        if not self.api_key:
            raise ValueError("Rerank API key is required.")
        if not self.base_url:
            raise ValueError("Rerank base URL is required.")

        scores: list[float] = []
        for start in range(0, len(documents), self.batch_size):
            batch = documents[start : start + self.batch_size]
            scores.extend(await self._rerank_batch(query=query, documents=batch))
        return scores

    async def _rerank_batch(self, *, query: str, documents: list[str]) -> list[float]:
        payload = self._build_payload(query=query, documents=documents)
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                self.base_url,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as error:
                body = response.text[:1000]
                raise ValueError(
                    f"Rerank request failed: status={response.status_code}, body={body}"
                ) from error
            data = response.json()

        raw_results = self._extract_results(data)
        ordered = sorted(raw_results, key=lambda item: int(item.get("index") or 0))
        scores = [float(item.get("relevance_score", 0.0)) for item in ordered]
        if len(scores) != len(documents):
            raise ValueError(f"Rerank returned {len(scores)} scores for {len(documents)} documents.")
        if self.normalize_scores:
            return [self._sigmoid(score) for score in scores]
        return scores

    @abstractmethod
    def _build_payload(self, *, query: str, documents: list[str]) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def _extract_results(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    @staticmethod
    def _sigmoid(value: float) -> float:
        try:
            return 1.0 / (1.0 + math.exp(-value))
        except OverflowError:
            return 0.0 if value < 0 else 1.0


class OpenAIRerankService(HTTPRerankService):
    def _build_payload(self, *, query: str, documents: list[str]) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "query": query,
            "documents": documents,
            "max_chunks_per_doc": self.max_length,
        }

    def _extract_results(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        return list(data.get("results") or [])


class DashScopeRerankService(HTTPRerankService):
    def _build_payload(self, *, query: str, documents: list[str]) -> dict[str, Any]:
        return {
            "model": self.model_name,
            "query": query,
            "documents": documents,
            "top_n": len(documents),
        }

    def _extract_results(self, data: dict[str, Any]) -> list[dict[str, Any]]:
        return list(data.get("results") or (data.get("output") or {}).get("results") or [])
