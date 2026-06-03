__all__ = ["KnowledgeQaRuntime", "build_knowledge_answer"]


def __getattr__(name: str):
    if name == "KnowledgeQaRuntime":
        from app.agents.buildin.chat_konwledge.runtime import KnowledgeQaRuntime

        return KnowledgeQaRuntime
    if name == "build_knowledge_answer":
        from app.agents.buildin.chat_konwledge.graph import build_knowledge_answer

        return build_knowledge_answer
    raise AttributeError(name)
