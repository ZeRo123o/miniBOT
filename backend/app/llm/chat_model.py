import json
import logging
from typing import Any

import httpx
from langchain_core.language_models import LanguageModelInput
from langchain_core.callbacks import AsyncCallbackManagerForLLMRun, CallbackManagerForLLMRun
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from langchain_core.runnables import Runnable
from langchain_core.tools import BaseTool
from langchain_core.utils.function_calling import convert_to_openai_tool
from pydantic import Field

logger = logging.getLogger(__name__)


class ModelRequestTimeoutError(RuntimeError):
    """OpenAI-compatible 模型服务在配置的读取超时内未返回。"""


class MiniBotChatModel(BaseChatModel):
    provider: str = "mock"
    model_name: str = "mock"
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"
    temperature: float = 0.2
    timeout_seconds: float = 180.0
    tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_choice: str | dict[str, Any] | None = None

    @property
    def _llm_type(self) -> str:
        """返回当前模型适配器的类型标识。"""
        return f"minibot-{self.provider}"

    def bind_tools(
        self,
        tools: list[BaseTool | dict[str, Any] | type],
        *,
        tool_choice: str | dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Runnable[LanguageModelInput, BaseMessage]:
        """绑定 LangChain 工具定义，并转换为 OpenAI-compatible tool schema。"""
        converted_tools = [convert_to_openai_tool(item) for item in tools]
        return self.model_copy(update={"tools": converted_tools, "tool_choice": tool_choice})

    def _generate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: CallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """同步生成模型回复，兼容 LangChain BaseChatModel 接口。"""
        if self.provider == "mock":
            return self._mock_result(messages)
        return self._openai_compatible_result(messages)

    async def _agenerate(
        self,
        messages: list[BaseMessage],
        stop: list[str] | None = None,
        run_manager: AsyncCallbackManagerForLLMRun | None = None,
        **kwargs: Any,
    ) -> ChatResult:
        """异步生成模型回复，供 create_agent 主流程调用。"""
        if self.provider == "mock":
            return self._mock_result(messages)
        return await self._aopenai_compatible_result(messages)

    def _mock_result(self, messages: list[BaseMessage]) -> ChatResult:
        """生成本地 mock 回复，便于无 API Key 时开发调试。"""
        last_user = next((message.content for message in reversed(messages) if isinstance(message, HumanMessage)), "")
        message = AIMessage(content=f"收到：{last_user}\n\n当前使用 mock 模型。配置真实 provider 后会调用大模型。")
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _openai_payload(self, messages: list[BaseMessage]) -> dict[str, Any]:
        """把 LangChain 消息和工具 schema 转成 OpenAI-compatible 请求体。"""
        payload: dict[str, Any] = {
            "model": self.model_name,
            "messages": [self._convert_message(message) for message in messages],
            "temperature": self.temperature,
        }
        if self.tools:
            payload["tools"] = self.tools
        if self.tool_choice:
            payload["tool_choice"] = self.tool_choice
        return payload

    def _openai_headers(self) -> dict[str, str]:
        """构造 OpenAI-compatible 请求头，并校验 API Key。"""
        if not self.api_key:
            raise ValueError("MINIBOT_OPENAI_API_KEY is required for OpenAI-compatible provider.")
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _openai_compatible_result(self, messages: list[BaseMessage]) -> ChatResult:
        """同步调用 OpenAI-compatible chat completions 接口。"""
        try:
            with httpx.Client(timeout=self._http_timeout()) as client:
                response = client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=self._openai_payload(messages),
                    headers=self._openai_headers(),
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as error:
            self._raise_timeout(error)
        return self._result_from_openai_data(data)

    async def _aopenai_compatible_result(self, messages: list[BaseMessage]) -> ChatResult:
        """异步调用 OpenAI-compatible chat completions 接口。"""
        try:
            async with httpx.AsyncClient(timeout=self._http_timeout()) as client:
                response = await client.post(
                    f"{self.base_url.rstrip('/')}/chat/completions",
                    json=self._openai_payload(messages),
                    headers=self._openai_headers(),
                )
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException as error:
            self._raise_timeout(error)
        return self._result_from_openai_data(data)

    def _http_timeout(self) -> httpx.Timeout:
        """连接超时保持较短，模型生成阶段使用可配置读取超时。"""
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
            f"模型服务在 {self.timeout_seconds:g} 秒内未返回结果"
        ) from error

    def _result_from_openai_data(self, data: dict[str, Any]) -> ChatResult:
        """把 OpenAI-compatible 响应转换为 LangChain ChatResult。"""
        raw_message = data["choices"][0]["message"]
        content = raw_message.get("content") or ""
        tool_calls = self._parse_tool_calls(raw_message.get("tool_calls") or [])
        message = AIMessage(
            content=content,
            tool_calls=tool_calls,
            response_metadata={"model": self.model_name, "raw": data},
        )
        return ChatResult(generations=[ChatGeneration(message=message)])

    def _convert_message(self, message: BaseMessage) -> dict[str, Any]:
        """把 LangChain message 转换为 OpenAI-compatible message 字典。"""
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
        """把 OpenAI-compatible 的 tool_calls 转成 LangChain AIMessage 可识别的结构。"""
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
