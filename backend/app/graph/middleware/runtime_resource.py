from app.graph.middleware.base import GraphHandler, GraphMiddleware
from app.graph.state import ChatState


class RuntimeResourceMiddleware(GraphMiddleware):
    def __init__(self) -> None:
        super().__init__(name="runtime_resources")

    async def __call__(self, state: ChatState, handler: GraphHandler) -> ChatState:
        state["mcps"] = state.get("mcps", [])
        state["skills"] = state.get("skills", [])
        state["subagents"] = state.get("subagents", [])
        return await handler(state)
