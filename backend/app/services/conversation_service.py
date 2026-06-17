from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ConversationMessage
from app.db.repositories import ConversationMessageRepository, ConversationRepository
from app.services.attachment_service import build_attachment_state_files


class ConversationService:
    def __init__(self, db: AsyncSession):
        """初始化会话和消息相关仓储。"""
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = ConversationMessageRepository(db)

    async def prepare_conversation(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int | None,
    ) -> Conversation:
        """创建或校验会话，并在空会话首次发送消息时自动命名。"""
        title = message[:24] or "新对话"
        if conversation_id is None:
            return await self.conversation_repo.create(user_id=user_id, title=title)

        conversation = await self.conversation_repo.get(conversation_id, user_id=user_id)
        if conversation is None:
            raise ValueError("Conversation not found.")

        existing_messages = await self.message_repo.list(conversation.id)
        if not existing_messages and conversation.title == "新对话":
            conversation = await self.conversation_repo.update(conversation, title=title)
        return conversation

    async def save_user_message(
        self,
        conversation_id: int,
        content: str,
        *,
        uploads: list[dict] | None = None,
    ) -> None:
        """保存用户消息。"""
        metadata = {"uploads": uploads or []} if uploads else None
        await self.message_repo.create(conversation_id, role="user", content=content, metadata=metadata)

    async def save_assistant_message(
        self,
        *,
        conversation_id: int,
        content: str,
        metadata: dict,
    ) -> None:
        """保存 assistant 回复和运行时元数据。"""
        await self.message_repo.create(
            conversation_id,
            role="assistant",
            content=content,
            metadata=metadata,
        )

    async def load_langchain_messages(self, conversation_id: int) -> list[BaseMessage]:
        """读取会话历史消息，并转换为 LangChain 消息格式。"""
        persisted_messages = await self.message_repo.list(conversation_id)
        return [
            converted
            for message in persisted_messages
            if (converted := self._to_langchain_message(message)) is not None
        ]

    async def load_attachment_state(self, conversation_id: int) -> tuple[list[dict], dict]:
        """Rebuild graph upload/file state from persisted user message metadata."""
        persisted_messages = await self.message_repo.list(conversation_id)
        uploads: list[dict] = []
        seen_paths: set[str] = set()
        for message in persisted_messages:
            if message.role != "user":
                continue
            metadata = message.metadata_ or {}
            for item in metadata.get("uploads") or []:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                if isinstance(path, str) and path in seen_paths:
                    continue
                if isinstance(path, str):
                    seen_paths.add(path)
                uploads.append(item)
        return uploads, build_attachment_state_files(uploads)

    def _to_langchain_message(self, message: ConversationMessage) -> BaseMessage | None:
        """把数据库消息转换成模型可消费的 LangChain message。"""
        if message.role == "user":
            return HumanMessage(content=message.content)
        if message.role == "assistant":
            return AIMessage(content=message.content)
        return None

    async def build_chat_response(
        self,
        *,
        conversation_id: int,
        user_id: str,
        answer: str,
        selection: dict,
        resources: dict[str, list[dict]],
    ) -> dict:
        """构造返回给前端的聊天响应。"""
        messages = await self.message_repo.list(conversation_id)
        conversation = await self.conversation_repo.get(conversation_id, user_id=user_id)
        if conversation is None:
            raise ValueError("Conversation not found.")

        return {
            "answer": answer,
            "conversation_id": conversation.id,
            "conversation": conversation.to_dict(),
            "messages": [message.to_dict() for message in messages],
            "selection": selection,
            "resources": resources,
        }
