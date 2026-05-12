from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph

from app.graph.middleware import RuntimeResourceMiddleware, SkillPromptMiddleware, compose_middlewares
from app.graph.state import ChatState


async def _assistant_node(state: ChatState) -> ChatState:
    messages = state.get("messages", [])
    last_user = next((m.content for m in reversed(messages) if isinstance(m, HumanMessage)), "")
    resource_names = {
        "mcps": [item["name"] for item in state.get("mcps", [])],
        "skills": [item["name"] for item in state.get("skills", [])],
        "subagents": [item["name"] for item in state.get("subagents", [])],
    }
    content = (
        f"收到：{last_user}\n\n"
        "当前启用资源："
        f"MCP={resource_names['mcps']}, "
        f"Skill={resource_names['skills']}, "
        f"Subagent={resource_names['subagents']}。\n"
        "这里是可替换的 LangChain/LangGraph 模型调用节点。"
    )
    return {**state, "messages": [*messages, AIMessage(content=content)]}


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
