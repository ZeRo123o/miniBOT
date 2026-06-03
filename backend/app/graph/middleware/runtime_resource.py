from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from app.agents.buildin.chatbot.context import AgentContext


class RuntimeResourceMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """在模型调用前规范化上下文中的资源列表，避免空值影响 prompt 构建。"""
        context = request.runtime.context
        if isinstance(context, AgentContext):
            context.mcps = context.mcps or []
            context.skills = context.skills or []
            context.subagents = context.subagents or []
            context.tools = context.tools or []
        return await handler(request)
