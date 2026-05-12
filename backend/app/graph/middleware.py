from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.graph.state import ChatState

GraphHandler = Callable[[ChatState], Awaitable[ChatState]]


@dataclass
class GraphMiddleware:
    name: str

    async def __call__(self, state: ChatState, handler: GraphHandler) -> ChatState:
        return await handler(state)


class RuntimeResourceMiddleware(GraphMiddleware):
    def __init__(self) -> None:
        super().__init__(name="runtime_resources")

    async def __call__(self, state: ChatState, handler: GraphHandler) -> ChatState:
        state["mcps"] = state.get("mcps", [])
        state["skills"] = state.get("skills", [])
        state["subagents"] = state.get("subagents", [])
        return await handler(state)


class SkillPromptMiddleware(GraphMiddleware):
    def __init__(self) -> None:
        super().__init__(name="skill_prompt")

    async def __call__(self, state: ChatState, handler: GraphHandler) -> ChatState:
        return await handler(state)


def compose_middlewares(middlewares: list[GraphMiddleware], final_handler: GraphHandler) -> GraphHandler:
    handler = final_handler
    for middleware in reversed(middlewares):
        next_handler = handler

        async def wrapped(state: ChatState, mw: GraphMiddleware = middleware, nxt: GraphHandler = next_handler) -> ChatState:
            return await mw(state, nxt)

        handler = wrapped
    return handler
