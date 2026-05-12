from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from app.graph.state import ChatState

GraphHandler = Callable[[ChatState], Awaitable[ChatState]]


@dataclass
class GraphMiddleware:
    name: str

    async def __call__(self, state: ChatState, handler: GraphHandler) -> ChatState:
        return await handler(state)
