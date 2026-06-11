from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.tools import BaseTool

from app.agents.buildin.chatbot.context import AgentContext


class RuntimeConfigMiddleware(AgentMiddleware):
    """注册候选运行时工具，并在每次模型调用前按 AgentContext 再次筛选。"""

    def __init__(self, tools: list[BaseTool]) -> None:
        super().__init__()
        self.tools = tools
        self._managed_tool_names = {tool.name for tool in tools}

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        context = request.runtime.context
        enabled_names = self._enabled_tool_names(context)

        # 保留知识库等其他 middleware 注入的工具，只过滤本中间件管理的运行时工具。
        visible_tools = [
            tool
            for tool in request.tools or []
            if tool.name not in self._managed_tool_names or tool.name in enabled_names
        ]
        return await handler(request.override(tools=visible_tools))

    def _enabled_tool_names(self, context: object) -> set[str]:
        """从已由服务层完成权限解析的上下文中提取工具白名单。"""
        if not isinstance(context, AgentContext):
            return set()
        return {
            str(item.get("name") or "").strip()
            for item in context.tools
            if item.get("name")
        }
