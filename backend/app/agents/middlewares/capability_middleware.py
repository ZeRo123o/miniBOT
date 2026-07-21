"""在每次模型调用前应用统一的工具暴露决策。"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable, Iterable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from app.agents.capabilities import CapabilityResolver, ResolvedCapabilities

logger = logging.getLogger(__name__)


class CapabilityMiddleware(AgentMiddleware):
    """保留可执行工具，同时仅向模型展示本轮获准的 Tool Schema。"""

    def __init__(
        self,
        *,
        agent_type: str,
        subagent_type: str | None = None,
        denied_tool_names: Iterable[str] = (),
        resolver: CapabilityResolver | None = None,
    ) -> None:
        super().__init__()
        self.agent_type = agent_type
        self.subagent_type = subagent_type
        self.denied_tool_names = frozenset(
            str(name or "").strip()
            for name in denied_tool_names
            if str(name or "").strip()
        )
        self.resolver = resolver or CapabilityResolver()

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        context = request.runtime.context
        state = request.state if isinstance(request.state, dict) else {}
        activated_skills = state.get("activated_skills", [])
        if not isinstance(activated_skills, list):
            activated_skills = []

        current_tools = list(request.tools or [])
        capabilities = await self.resolver.resolve(
            context=context,
            agent_type=self.agent_type,
            subagent_type=self.subagent_type or getattr(context, "subagent_type", None),
            activated_skills=activated_skills,
            available_tool_names=[
                str(getattr(tool, "name", "") or "")
                for tool in current_tools
            ],
            denied_tool_names=self.denied_tool_names,
        )
        setattr(context, "_resolved_capabilities", capabilities)

        filtered_tools = [
            tool
            for tool in current_tools
            if str(getattr(tool, "name", "") or "")
            in capabilities.model_visible_tool_names
        ]
        logger.info(
            "Agent capabilities resolved: agent_type=%s subagent_type=%s "
            "executable=%s model_visible=%s",
            self.agent_type,
            self.subagent_type or getattr(context, "subagent_type", ""),
            sorted(capabilities.executable_tool_names),
            sorted(capabilities.model_visible_tool_names),
        )
        return await handler(request.override(tools=filtered_tools))

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Any],
    ) -> Any:
        """同步执行工具前校验当前 Agent 的执行资格。"""
        if not self._is_tool_call_executable(request):
            return self._denied_tool_message(request)
        return handler(request)

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[Any]],
    ) -> Any:
        """异步执行工具前校验当前 Agent 的执行资格。"""
        if not self._is_tool_call_executable(request):
            return self._denied_tool_message(request)
        return await handler(request)

    @staticmethod
    def _is_tool_call_executable(request: ToolCallRequest) -> bool:
        """只允许执行最近一次模型调用实际获准看到的工具。"""
        capabilities = getattr(
            request.runtime.context,
            "_resolved_capabilities",
            None,
        )
        if not isinstance(capabilities, ResolvedCapabilities):
            # 模型驱动的 ToolCall 正常情况下必定先经过 awrap_model_call；
            # 缺少决策结果时失败关闭，避免 checkpoint 或外部输入绕过授权。
            return False
        tool_name = str(request.tool_call.get("name") or "").strip()
        return (
            tool_name in capabilities.executable_tool_names
            and tool_name in capabilities.model_visible_tool_names
        )

    def _denied_tool_message(self, request: ToolCallRequest) -> ToolMessage:
        """返回稳定且不泄漏策略细节的越权错误。"""
        tool_name = str(request.tool_call.get("name") or "").strip()
        tool_call_id = str(request.tool_call.get("id") or "unauthorized-tool-call")
        logger.warning(
            "Agent tool execution denied: agent_type=%s subagent_type=%s tool=%s",
            self.agent_type,
            self.subagent_type
            or getattr(request.runtime.context, "subagent_type", ""),
            tool_name,
        )
        return ToolMessage(
            content="当前 Agent 无权执行该工具。",
            tool_call_id=tool_call_id,
            name=tool_name or None,
            status="error",
        )
