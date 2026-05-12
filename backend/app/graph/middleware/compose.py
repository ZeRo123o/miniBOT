from app.graph.middleware.base import GraphHandler, GraphMiddleware
from app.graph.state import ChatState


def compose_middlewares(middlewares: list[GraphMiddleware], final_handler: GraphHandler) -> GraphHandler:
    handler = final_handler
    for middleware in reversed(middlewares):
        next_handler = handler

        async def wrapped(
            state: ChatState,
            mw: GraphMiddleware = middleware,
            nxt: GraphHandler = next_handler,
        ) -> ChatState:
            return await mw(state, nxt)

        handler = wrapped
    return handler
