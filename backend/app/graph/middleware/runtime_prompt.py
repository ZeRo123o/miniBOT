from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage

from app.agent.context import AgentContext
from app.graph.prompt import build_system_prompt


class RuntimePromptMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """在每次模型调用前动态生成 system prompt，并注入到模型请求中。"""
        context = request.runtime.context
        if isinstance(context, AgentContext):
            system_prompt = build_system_prompt(context)
            request = request.override(system_message=SystemMessage(content=system_prompt))
        return await handler(request)
