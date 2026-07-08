import logging
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services import ConversationService, ResourceService, SelectionService

logger = logging.getLogger(__name__)


@dataclass
class RuntimeResult:
    answer: str
    metadata: dict[str, Any]
    response_extra: dict[str, Any] = field(default_factory=dict)


class BaseChatRuntime(ABC):
    """Shared conversation lifecycle for built-in chat runtimes."""

    def __init__(self, db: AsyncSession):
        self.conversation_service = ConversationService(db)
        self.selection_service = SelectionService(db)
        self.resource_service = ResourceService(db)

    async def run(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int | None = None,
        uploads: list[dict] | None = None,
        model_spec: str | None = None,
    ) -> dict:
        model_spec = (model_spec or "").strip()
        if not model_spec:
            raise ValueError("请选择聊天模型后再发送消息。")
        logger.info(
            "Runtime run started: user_id=%s conversation_id=%s message_chars=%s",
            user_id,
            conversation_id,
            len(message),
        )
        conversation = await self.conversation_service.prepare_conversation(
            user_id=user_id,
            message=message,
            conversation_id=conversation_id,
        )
        prepared_conversation_id = conversation.id
        logger.info(
            "Runtime conversation prepared: user_id=%s conversation_id=%s",
            user_id,
            prepared_conversation_id,
        )
        upload_items = list(uploads or [])
        await self.conversation_service.save_user_message(
            prepared_conversation_id,
            message,
            uploads=upload_items,
        )
        logger.info(
            "Runtime user message saved: conversation_id=%s",
            prepared_conversation_id,
        )

        knowledge_selection = await self.selection_service.get_or_default(user_id)
        resources = await self.resource_service.resolve_enabled_resources(user_id)
        logger.info(
            "Runtime resources resolved: conversation_id=%s mcps=%s skills=%s tools=%s",
            prepared_conversation_id,
            len(resources.get("mcps", [])),
            len(resources.get("skills", [])),
            len(resources.get("tools", [])),
        )
        result = await self._generate_result(
            user_id=user_id,
            message=message,
            conversation_id=prepared_conversation_id,
            knowledge_selection=knowledge_selection,
            resources=resources,
            uploads=upload_items,
            model_spec=model_spec,
        )

        await self.conversation_service.save_assistant_message(
            conversation_id=prepared_conversation_id,
            content=result.answer,
            metadata=result.metadata,
        )
        logger.info(
            "Runtime assistant message saved: conversation_id=%s answer_chars=%s",
            prepared_conversation_id,
            len(result.answer),
        )
        response = await self.conversation_service.build_chat_response(
            conversation_id=prepared_conversation_id,
            user_id=user_id,
            answer=result.answer,
            selection=knowledge_selection,
            resources=resources,
        )
        logger.info("Runtime run completed: conversation_id=%s", prepared_conversation_id)
        return self._build_response(response, result)

    async def run_stream(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int | None = None,
        uploads: list[dict] | None = None,
        model_spec: str | None = None,
    ) -> AsyncIterator[dict]:
        model_spec = (model_spec or "").strip()
        if not model_spec:
            raise ValueError("请选择聊天模型后再发送消息。")
        logger.info(
            "Runtime stream started: user_id=%s conversation_id=%s message_chars=%s",
            user_id,
            conversation_id,
            len(message),
        )
        conversation = await self.conversation_service.prepare_conversation(
            user_id=user_id,
            message=message,
            conversation_id=conversation_id,
        )
        prepared_conversation_id = conversation.id
        prepared_conversation = conversation.to_dict()
        logger.info(
            "Runtime stream conversation prepared: user_id=%s conversation_id=%s",
            user_id,
            prepared_conversation_id,
        )
        upload_items = list(uploads or [])
        await self.conversation_service.save_user_message(
            prepared_conversation_id,
            message,
            uploads=upload_items,
        )
        logger.info(
            "Runtime stream user message saved: conversation_id=%s",
            prepared_conversation_id,
        )
        yield {
            "type": "conversation",
            "conversation_id": prepared_conversation_id,
            "conversation": prepared_conversation,
        }

        knowledge_selection = await self.selection_service.get_or_default(user_id)
        resources = await self.resource_service.resolve_enabled_resources(user_id)
        logger.info(
            "Runtime stream resources resolved: conversation_id=%s mcps=%s skills=%s tools=%s",
            prepared_conversation_id,
            len(resources.get("mcps", [])),
            len(resources.get("skills", [])),
            len(resources.get("tools", [])),
        )
        result: RuntimeResult | None = None
        async for stream_item in self._generate_stream_result(
            user_id=user_id,
            message=message,
            conversation_id=prepared_conversation_id,
            knowledge_selection=knowledge_selection,
            resources=resources,
            uploads=upload_items,
            model_spec=model_spec,
        ):
            if isinstance(stream_item, RuntimeResult):
                result = stream_item
            else:
                yield stream_item
        if result is None:
            raise RuntimeError("Runtime stream ended without a final result.")

        await self.conversation_service.save_assistant_message(
            conversation_id=prepared_conversation_id,
            content=result.answer,
            metadata=result.metadata,
        )
        logger.info(
            "Runtime stream assistant message saved: conversation_id=%s answer_chars=%s",
            prepared_conversation_id,
            len(result.answer),
        )
        response = await self.conversation_service.build_chat_response(
            conversation_id=prepared_conversation_id,
            user_id=user_id,
            answer=result.answer,
            selection=knowledge_selection,
            resources=resources,
        )
        logger.info("Runtime stream done event ready: conversation_id=%s", prepared_conversation_id)
        yield {"type": "done", **self._build_response(response, result)}

    @abstractmethod
    async def _generate_result(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int,
        knowledge_selection: dict,
        resources: dict[str, list[dict]],
        uploads: list[dict],
        model_spec: str | None = None,
    ) -> RuntimeResult:
        """Generate the assistant answer."""

    async def _generate_stream_result(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int,
        knowledge_selection: dict,
        resources: dict[str, list[dict]],
        uploads: list[dict],
        model_spec: str | None = None,
    ) -> AsyncIterator[dict | RuntimeResult]:
        """Yield runtime SSE events followed by the final result; default runtimes have no events."""
        yield await self._generate_result(
            user_id=user_id,
            message=message,
            conversation_id=conversation_id,
            knowledge_selection=knowledge_selection,
            resources=resources,
            uploads=uploads,
            model_spec=model_spec,
        )

    def _build_response(self, response: dict, result: RuntimeResult) -> dict:
        response.update(result.response_extra)
        return response
