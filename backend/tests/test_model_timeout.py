from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from langchain_core.messages import HumanMessage

from app.agents.buildin.chatbot.runtime import AgentRuntime
from app.llm.chat_model import MiniBotChatModel, ModelRequestTimeoutError


class TimeoutAsyncClient:
    def __init__(self, *args, **kwargs):
        self.timeout = kwargs.get("timeout")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def post(self, *args, **kwargs):
        raise httpx.ReadTimeout("upstream timed out")


class ModelTimeoutTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_model_converts_httpx_timeout(self):
        model = MiniBotChatModel(
            provider="openai-compatible",
            model_name="test-model",
            api_key="test-key",
            timeout_seconds=123,
        )

        with patch("app.llm.chat_model.httpx.AsyncClient", TimeoutAsyncClient):
            with self.assertRaisesRegex(
                ModelRequestTimeoutError,
                "123 秒",
            ):
                await model._aopenai_compatible_result(
                    [HumanMessage(content="hello")]
                )

    async def test_runtime_returns_friendly_timeout_result(self):
        runtime = AgentRuntime.__new__(AgentRuntime)
        runtime.conversation_service = SimpleNamespace(
            load_langchain_messages=self._load_messages
        )
        resources = {"skills": [], "tools": [], "mcps": []}

        class TimeoutAgent:
            async def ainvoke(self, *args, **kwargs):
                raise ModelRequestTimeoutError("timeout")

        with patch(
            "app.agents.buildin.chatbot.runtime.build_chat_agent",
            return_value=TimeoutAgent(),
        ):
            result = await runtime._generate_result(
                user_key="default",
                message="hello",
                conversation_id=7,
                selection={"knowledge_base_ids": []},
                resources=resources,
            )

        self.assertEqual(result.metadata["error"], "model_timeout")
        self.assertIn("响应超时", result.answer)

    @staticmethod
    async def _load_messages(_conversation_id):
        return [HumanMessage(content="hello")]


if __name__ == "__main__":
    unittest.main()
