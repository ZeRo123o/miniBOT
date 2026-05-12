from app.graph.middleware.base import GraphHandler, GraphMiddleware
from app.graph.state import ChatState


class SkillPromptMiddleware(GraphMiddleware):
    def __init__(self) -> None:
        super().__init__(name="skill_prompt")

    async def __call__(self, state: ChatState, handler: GraphHandler) -> ChatState:
        skill_names = [item.get("name", "") for item in state.get("skills", [])]
        if skill_names:
            runtime = dict(state.get("runtime", {}))
            runtime["skill_prompt"] = f"当前启用 Skills: {', '.join(skill_names)}"
            state["runtime"] = runtime
        return await handler(state)
