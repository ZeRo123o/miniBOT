from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx

from app.knowledge.embedding.openai import OpenAIEmbeddingService, resolve_embedding_batch_size
from app.llm.providers.builtin import BUILTIN_PROVIDERS
from app.llm.providers.service import _test_embedding_model


class EmbeddingBatchLimitTests(unittest.IsolatedAsyncioTestCase):
    def test_dashscope_builtin_embedding_uses_safe_default_batch_size(self):
        provider = next(item for item in BUILTIN_PROVIDERS if item["provider_id"] == "alibaba")
        model = next(item for item in provider["enabled_models"] if item["id"] == "text-embedding-v4")

        self.assertEqual(model["batch_size"], 10)

    def test_dashscope_batch_size_is_clamped_to_known_limit(self):
        batch_size = resolve_embedding_batch_size(
            provider_id="alibaba",
            model_name="text-embedding-v4",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
            configured_batch_size=40,
        )

        self.assertEqual(batch_size, 10)

    async def test_embedding_retries_with_limit_from_batch_size_error(self):
        calls: list[int] = []

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

            async def post(self, url, **kwargs):
                input_count = len(kwargs["json"]["input"])
                calls.append(input_count)
                request = httpx.Request("POST", url)
                if input_count > 2:
                    return httpx.Response(
                        400,
                        request=request,
                        text=(
                            '{"error":{"message":"batch size is invalid, '
                            'it should not be larger than 2.: input.contents"}}'
                        ),
                    )
                return httpx.Response(
                    200,
                    request=request,
                    json={"data": [{"index": index, "embedding": [float(index)]} for index in range(input_count)]},
                )

        service = OpenAIEmbeddingService(
            model_name="custom-embedding",
            api_key="test-key",
            base_url="https://example.com/v1",
            dimension=1,
            batch_size=4,
        )

        with patch("app.knowledge.embedding.openai.httpx.AsyncClient", FakeAsyncClient):
            embeddings = await service.embed_texts(["a", "b", "c", "d"])

        self.assertEqual(calls, [4, 2, 2])
        self.assertEqual(embeddings, [[0.0], [1.0], [0.0], [1.0]])
        self.assertEqual(service.batch_size, 2)

    async def test_embedding_model_status_uses_effective_batch_size(self):
        captured: dict[str, int] = {}

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, traceback):
                return False

            async def post(self, url, **kwargs):
                input_count = len(kwargs["json"]["input"])
                captured["input_count"] = input_count
                request = httpx.Request("POST", url)
                return httpx.Response(
                    200,
                    request=request,
                    json={"data": [{"index": index, "embedding": [0.1] * 1024} for index in range(input_count)]},
                )

        info = SimpleNamespace(
            provider_id="alibaba",
            model_id="text-embedding-v4",
            model_type="embedding",
            spec="alibaba:text-embedding-v4",
            api_key="test-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/embeddings",
            headers={},
            dimension=1024,
            batch_size=40,
        )

        with patch("app.llm.providers.service.httpx.AsyncClient", FakeAsyncClient):
            result = await _test_embedding_model(info)

        self.assertEqual(captured["input_count"], 10)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["batch_size"], 10)


if __name__ == "__main__":
    unittest.main()
