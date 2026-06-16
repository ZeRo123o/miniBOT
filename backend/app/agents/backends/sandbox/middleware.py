from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import replace as dataclass_replace
from typing import NotRequired

from langchain.agents import AgentState
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command


class SandboxMiddlewareState(AgentState):
    sandbox: NotRequired[dict | None]


class SandboxMiddleware(AgentMiddleware):
    """持久化文件工具延迟创建的 sandbox_id，不主动冷启动容器。"""

    state_schema = SandboxMiddlewareState

    @staticmethod
    def _sandbox_id(request: ToolCallRequest) -> str | None:
        state = getattr(request.runtime, "state", None)
        if not isinstance(state, dict):
            return None
        sandbox = state.get("sandbox")
        if not isinstance(sandbox, dict):
            return None
        value = sandbox.get("sandbox_id")
        return value if isinstance(value, str) else None

    @staticmethod
    def _attach_update(
        result: ToolMessage | Command,
        sandbox_id: str,
    ) -> ToolMessage | Command:
        sandbox_update = {"sandbox": {"sandbox_id": sandbox_id}}
        if isinstance(result, ToolMessage):
            return Command(
                update={
                    **sandbox_update,
                    "messages": [result],
                }
            )
        if isinstance(result.update, dict):
            return dataclass_replace(
                result,
                update={**result.update, **sandbox_update},
            )
        return result

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        before = self._sandbox_id(request)
        result = handler(request)
        after = self._sandbox_id(request)
        if before is None and after is not None:
            return self._attach_update(result, after)
        return result

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[
            [ToolCallRequest],
            Awaitable[ToolMessage | Command],
        ],
    ) -> ToolMessage | Command:
        before = self._sandbox_id(request)
        result = await handler(request)
        after = self._sandbox_id(request)
        if before is None and after is not None:
            return self._attach_update(result, after)
        return result
