from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.buildin.chatbot.prompt import build_runtime_prompt
from app.agents.middlewares.system_message import append_system_message


class RuntimePromptMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """在每次模型调用前增量追加资源和工具策略。"""
        context = request.runtime.context
        if isinstance(context, AgentContext):
            runtime_prompt = build_runtime_prompt(context)
            request = request.override(
                system_message=append_system_message(request.system_message, runtime_prompt)
            )
        return await handler(request)
