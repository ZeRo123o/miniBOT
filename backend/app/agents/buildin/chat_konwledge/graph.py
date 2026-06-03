from app.agents.buildin.chat_konwledge.prompt import (
    KNOWLEDGE_CONTEXT_REPLY_TEMPLATE,
    KNOWLEDGE_EMPTY_REPLY_TEMPLATE,
)


def build_knowledge_answer(*, question: str, citations: list[dict]) -> str:
    """Build the knowledge QA answer from retrieved citation chunks."""
    if not citations:
        return KNOWLEDGE_EMPTY_REPLY_TEMPLATE.format(question=question)

    joined_context = "\n\n".join(item.get("content", "") for item in citations)
    return KNOWLEDGE_CONTEXT_REPLY_TEMPLATE.format(context=joined_context)
