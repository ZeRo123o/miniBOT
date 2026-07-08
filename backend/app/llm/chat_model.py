import json
import logging
from collections.abc import AsyncIterator
from typing import Any

import httpx
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models import LanguageModelInput
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatGenerationChunk, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

logger = logging.getLogger(__name__)


class ModelRequestTimeoutError(RuntimeError):
    """Raised when the configured model endpoint does not respond in time."""


class MiniBotChatModel(BaseChatModel):
    provider: str = "openai-compatible"
    model_name: str = ""
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.2
    timeout_seconds: float = 180.0
    request_headers: dict[str, str] = Field(default_factory=dict)
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None

    @property
    def _llm_type(self) -> str:
        return f"minibot-{self.provider}"

    def bind_tools(
        self,
        tools: list[BaseTool | dict[str, Any] | type],
        *,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        converted_tools = [convert_to_openai_tool(item) for item in tools]
        return self.model_copy(update={"tools": converted_tools, "tool_choice": tool_choice})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return self._openai_compatible_result(messages, stop=stop)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        return await self._aopenai_compatible_result(messages, stop=stop)

    async def _astream(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[ChatGenerationChunk]:
        payload = self._openai_payload(messages, stop=stop)
        payload["stream"] = True
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout()) as client:
                async with client.stream(
                    "POST",
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=payload,
                    headers=self._openai_headers(),
                ) as response:
                    response.raise_for_status()
                    async for line in response.aiter_lines():
                        chunk = self._stream_chunk_from_line(line)
                        if chunk is not None:
                            yield chunk
        except httpx.TimeoutException as error:
            self._raise_timeout(error)

    def _stream_chunk_from_line(self, line: str) -> ChatGenerationChunk | None:
        if not line.startswith("data:"):
            return None
        raw_data = line[5:].strip()
        if not raw_data or raw_data == "[DONE]":
            return None
        try:
            data = json.loads(raw_data)
        except json.JSONDecodeError:
            logger.warning("Ignoring malformed OpenAI-compatible stream chunk")
            return None

        choices = data.get("choices") or []
        if not choices:
            return None
        choice = choices[0] or {}
        delta = choice.get("delta") or {}
        tool_call_chunks = []
        for item in delta.get("tool_calls") or []:
            function = item.get("function") or {}
            tool_call_chunks.append(
                {
                    "name": function.get("name"),
                    "args": function.get("arguments") or "",
                    "id": item.get("id"),
                    "index": item.get("index", 0),
                    "type": "tool_call_chunk",
                }
            )
        finish_reason = choice.get("finish_reason")
        message = AIMessageChunk(
            content=delta.get("content") or "",
            tool_call_chunks=tool_call_chunks,
            id=data.get("id"),
            response_metadata={"model": data.get("model") or self.model_name},
            chunk_position="last" if finish_reason else None,
        )
        return ChatGenerationChunk(
            message=message,
            generation_info={"finish_reason": finish_reason} if finish_reason else None,
        )

    def _openai_payload(self, messages: list[BaseMessage], stop: list[str] | None = None) -> dict[str, Any]:
        if not self.model_name:
            raise ValueError("Model name is not configured.")
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [self._convert_message(message) for message in messages],
            "temperature": self.temperature,
        }
        if stop:
            payload["stop"] = stop
        if self.tools:
            payload["tools"] = self.tools
        if self.tool_choice:
            payload["tool_choice"] = self.tool_choice
        return payload

    def _openai_headers(self) -> dict[str, str]:
        if not self.api_key:
            raise ValueError("Model API key is not configured. Please set it on the model config page or via api_key_env.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            **self.request_headers,
        }

    def _openai_compatible_result(self, messages: list[BaseMessage], stop: list[str] | None = None) -> ChatResult:
        try:
            with httpx.Client(timeout=self._http_timeout()) as client:
                response = client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=self._openai_payload(messages, stop=stop),
                    headers=self._openai_headers(),
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as error:
            self._raise_timeout(error)
        return self._result_from_openai_data(data)

    async def _aopenai_compatible_result(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
    ) -> ChatResult:
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout()) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=self._openai_payload(messages, stop=stop),
                    headers=self._openai_headers(),
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as error:
            self._raise_timeout(error)
        return self._result_from_openai_data(data)

    def _http_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            connect=min(20.0, self.timeout_seconds),
            read=self.timeout_seconds,
            write=30.0,
            pool=30.0,
        )

    def _raise_timeout(self, error: httpx.TimeoutException) -> None:
        logger.warning(
            "Model request timed out: provider=%s model=%s timeout_seconds=%s",
            self.provider,
            self.model_name,
            self.timeout_seconds,
        )
        raise ModelRequestTimeoutError(
            f"Model service did not respond within {self.timeout_seconds:g} seconds."
        ) from error

    def _result_from_openai_data(self, data: dict[str, Any]) -> ChatResult:
        raw_message = data["choices"][0]["message"]
        message = AIMessage(
            content=raw_message.get("content") or "",
            tool_calls=self._parse_tool_calls(raw_message.get("tool_calls") or []),
            response_metadata={"model": self.model_name, "raw": data},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _convert_message(self, message: BaseMessage) -> dict[str, Any]:
        role = getattr(message, "type", "human")
        if role == "human":
            role = "user"
        elif role == "ai":
            role = "assistant"
        payload: dict[str, Any] = {"role": role, "content": message.content}
        if isinstance(message, AIMessage) and message.tool_calls:
            payload["tool_calls"] = [
                {
                    "id": item["id"],
                    "type": "function",
                    "function": {
                        "name": item["name"],
                        "arguments": json.dumps(item["args"], ensure_ascii=False),
                    },
                }
                for item in message.tool_calls
            ]
        if isinstance(message, ToolMessage):
            payload["role"] = "tool"
            payload["tool_call_id"] = message.tool_call_id
        return payload

    def _parse_tool_calls(self, tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        parsed = []
        for item in tool_calls:
            function = item.get("function") or {}
            raw_args = function.get("arguments") or "{}"
            try:
                args = json.loads(raw_args)
            except json.JSONDecodeError:
                args = {"raw_arguments": raw_args}
            parsed.append(
                {
                    "name": function.get("name", ""),
                    "args": args,
                    "id": item.get("id", ""),
                    "type": "tool_call",
                }
            )
        return parsed
