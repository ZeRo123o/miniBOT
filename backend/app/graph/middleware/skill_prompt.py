from collections.abc import Callable

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse

from app.agent.context import AgentContext


class SkillPromptMiddleware(AgentMiddleware):
    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        """根据当前启用的 Skill 资源补充运行时提示词片段。"""
        context = request.runtime.context
        if isinstance(context, AgentContext) and context.skills:
            skill_names = [
                item.get("display_name") or item.get("name", "")
                for item in context.skills
                if item.get("name")
            ]
            context.skill_prompt = f"当前启用 Skills: {', '.join(skill_names)}"
        return await handler(request)
