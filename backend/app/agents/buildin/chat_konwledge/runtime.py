from app.agents.buildin.chat_konwledge.graph import build_knowledge_answer
from app.agents.runtime_base import BaseChatRuntime, RuntimeResult


class KnowledgeQaRuntime(BaseChatRuntime):
    """Enterprise knowledge QA workflow.

    The retrieval hook is intentionally isolated so pgvector-backed document
    search can be added without changing the chat API or frontend mode flow.
    """

    mode = "knowledge"

    async def _generate_result(
        self,
        *,
        user_key: str,
        message: str,
        conversation_id: int,
        selection: dict,
        resources: dict[str, list[dict]],
    ) -> RuntimeResult:
        citations = await self._retrieve_citations(user_key=user_key, question=message)
        answer = build_knowledge_answer(question=message, citations=citations)
        return RuntimeResult(
            answer=answer,
            metadata={
                "mode": "knowledge",
                "workflow": "knowledge_qa",
                "citations": citations,
                "resources": resources,
            },
            response_extra={"citations": citations},
        )

    async def _retrieve_citations(self, *, user_key: str, question: str) -> list[dict]:
        """Return ranked knowledge chunks for the question.

        This is the future pgvector / hybrid-search integration point. Returning
        an empty list keeps the workflow honest until documents are indexed.
        """
        return []
