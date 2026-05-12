from langchain_core.messages import AIMessage, BaseMessage, SystemMessage
from langgraph.graph import END, START, StateGraph

from app.core.config import get_settings
from app.graph.middleware import RuntimeResourceMiddleware, SkillPromptMiddleware, compose_middlewares
from app.graph.state import ChatState
from app.llm import get_chat_model


def _resource_context(state: ChatState) -> str:
    mcps = [item.get("name", "") for item in state.get("mcps", [])]
    skills = [item.get("name", "") for item in state.get("skills", [])]
    subagents = [item.get("name", "") for item in state.get("subagents", [])]
    return (
        "当前启用资源：\n"
        f"- MCP: {mcps or '无'}\n"
        f"- Skill: {skills or '无'}\n"
        f"- Subagent: {subagents or '无'}"
    )


def _build_model_messages(state: ChatState) -> list[BaseMessage]:
    settings = get_settings()
    runtime = state.get("runtime", {})
    system_parts = [
        settings.default_system_prompt,
        _resource_context(state),
    ]
    if runtime.get("skill_prompt"):
        system_parts.append(runtime["skill_prompt"])
    return [
        SystemMessage(content="\n\n".join(system_parts)),
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
