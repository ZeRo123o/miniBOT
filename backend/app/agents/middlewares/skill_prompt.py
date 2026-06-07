from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.buildin.chatbot.prompt import build_skill_prompt
from app.agents.middlewares.system_message import append_system_message


class SkillPromptMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """根据当前启用的 Skill 元数据增量追加提示词片段。"""
        context = request.runtime.context
        if isinstance(context, AgentContext):
            skill_prompt = build_skill_prompt(context)
            if skill_prompt:
                request = request.override(
                    system_message=append_system_message(request.system_message, skill_prompt)
                )
        return await handler(request)
