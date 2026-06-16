from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage
from langchain_core.tools import BaseTool

from app.agents.buildin.chatbot.context import AgentContext


class RuntimeConfigMiddleware(AgentMiddleware):
    """注册候选运行时工具，并在每次模型调用前按 AgentContext 再次筛选。"""

    def __init__(
        self,
        tools: list[BaseTool],
        *,
        system_prompt_context_name: str = "system_prompt",
        enable_system_prompt_override: bool = True,
        enable_tools_override: bool = True,
    ) -> None:
        super().__init__()
        self.tools = tools
        self._managed_tool_names = {tool.name for tool in tools}
        self.system_prompt_context_name = system_prompt_context_name
        self.enable_system_prompt_override = enable_system_prompt_override
        self.enable_tools_override = enable_tools_override

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        runtime_context = request.runtime.context
        overrides: dict[str, Any] = {}

        if self.enable_tools_override:
            enabled_names = self._enabled_tool_names(runtime_context)
            # 保留知识库等其他 middleware 注入的工具，只筛选本中间件管理的工具。
            overrides["tools"] = [
                tool
                for tool in request.tools or []
                if tool.name not in self._managed_tool_names
                or tool.name in enabled_names
            ]

        # 与 Yuxi 一致：每次模型调用都从 runtime context 读取最新 system_prompt。
        if self.enable_system_prompt_override:
            system_prompt = (
                getattr(runtime_context, self.system_prompt_context_name, "") or ""
            )
            current_datetime = getattr(runtime_context, "current_datetime", "") or ""
            merged_system_prompt = (
                f"当前时间：{current_datetime}\n\n{system_prompt}"
                if current_datetime
                else system_prompt
            )
            content_blocks = (
                list(request.system_message.content_blocks)
                if request.system_message
                else []
            )
            overrides["system_message"] = SystemMessage(
                content=[
                    *content_blocks,
                    {"type": "text", "text": merged_system_prompt},
                ]
            )

        if overrides:
            request = request.override(**overrides)
        return await handler(request)

    def _enabled_tool_names(self, context: object) -> set[str]:
        """从已由服务层完成权限解析的上下文中提取工具白名单。"""
        if not isinstance(context, AgentContext):
            return set()
        return {
            str(item.get("name") or "").strip()
            for item in context.tools
            if item.get("name")
            and (item.get("config") or {}).get("expose_directly", True) is not False
        }
