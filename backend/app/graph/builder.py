from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.graph.middleware import RuntimeResourceMiddleware, SkillPromptMiddleware, compose_middlewares
from app.graph.prompt import build_system_prompt
from app.graph.state import ChatState
from app.llm import get_chat_model


def _build_model_messages(state: ChatState) -> list[BaseMessage]:
    settings = get_settings()
    return [
        SystemMessage(content=build_system_prompt(state, settings.default_system_prompt)),
        *state.get("messages", []),
    ]


async def _assistant_node(state: ChatState) -> ChatState:
    model = get_chat_model()
    response = await model.ainvoke(_build_model_messages(state))
    if not isinstance(response, AIMessage):
        response = AIMessage(content=str(response.content))
    return {**state, "messages": [*state.get("messages", []), response]}


async def _agent_node(state: ChatState) -> ChatState:
    handler = compose_middlewares(
        [
            RuntimeResourceMiddleware(),
            SkillPromptMiddleware(),
        ],
        _assistant_node,
    )
    return await handler(state)


def build_chat_graph():
    graph = StateGraph(ChatState)
    graph.add_node("agent", _agent_node)
    graph.add_edge(START, "agent")
    graph.add_edge("agent", END)
    return graph.compile()
