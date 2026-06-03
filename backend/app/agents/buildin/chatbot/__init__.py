__all__ = ["AgentContext", "AgentRuntime", "build_chat_agent", "build_chat_graph"]


def __getattr__(name: str):
    if name == "AgentContext":
        from app.agents.buildin.chatbot.context import AgentContext

        return AgentContext
    if name == "AgentRuntime":
        from app.agents.buildin.chatbot.runtime import AgentRuntime

        return AgentRuntime
    if name in {"build_chat_agent", "build_chat_graph"}:
        from app.agents.buildin.chatbot.graph import build_chat_agent, build_chat_graph

        return {"build_chat_agent": build_chat_agent, "build_chat_graph": build_chat_graph}[name]
    raise AttributeError(name)
