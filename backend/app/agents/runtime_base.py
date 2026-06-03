import asyncio
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

    mode: str

    def __init__(self, db: AsyncSession):
        self.conversation_service = ConversationService(db)
        self.selection_service = SelectionService(db)
        self.resource_service = ResourceService(db)

    async def run(self, *, user_key: str, message: str, conversation_id: int | None = None) -> dict:
        logger.info(
            "Runtime run started: mode=%s user_key=%s conversation_id=%s message_chars=%s",
            self.mode,
            user_key,
            conversation_id,
            len(message),
        )
        conversation = await self.conversation_service.prepare_conversation(
            user_key=user_key,
            message=message,
            conversation_id=conversation_id,
        )
        prepared_conversation_id = conversation.id
        logger.info(
            "Runtime conversation prepared: mode=%s user_key=%s conversation_id=%s",
            self.mode,
            user_key,
            prepared_conversation_id,
        )
        await self.conversation_service.save_user_message(prepared_conversation_id, message)
        logger.info(
            "Runtime user message saved: mode=%s conversation_id=%s",
            self.mode,
            prepared_conversation_id,
        )

        selection = await self.selection_service.get_or_default(user_key)
        resources = await self.resource_service.resolve_for_selection(selection)
        logger.info(
            "Runtime resources resolved: mode=%s conversation_id=%s mcps=%s skills=%s subagents=%s tools=%s",
            self.mode,
            prepared_conversation_id,
            len(resources.get("mcps", [])),
            len(resources.get("skills", [])),
            len(resources.get("subagents", [])),
            len(resources.get("tools", [])),
        )
        result = await self._generate_result(
            user_key=user_key,
            message=message,
            conversation_id=prepared_conversation_id,
            selection=selection,
            resources=resources,
        )

        await self.conversation_service.save_assistant_message(
            conversation_id=prepared_conversation_id,
            content=result.answer,
            metadata=result.metadata,
        )
        logger.info(
            "Runtime assistant message saved: mode=%s conversation_id=%s answer_chars=%s",
            self.mode,
            prepared_conversation_id,
            len(result.answer),
        )
        response = await self.conversation_service.build_chat_response(
            conversation_id=prepared_conversation_id,
            user_key=user_key,
            answer=result.answer,
            selection=selection,
            resources=resources,
        )
        logger.info("Runtime run completed: mode=%s conversation_id=%s", self.mode, prepared_conversation_id)
        return self._build_response(response, result)

    async def run_stream(
        self,
        *,
        user_key: str,
        message: str,
        conversation_id: int | None = None,
    ) -> AsyncIterator[dict]:
        logger.info(
            "Runtime stream started: mode=%s user_key=%s conversation_id=%s message_chars=%s",
            self.mode,
            user_key,
            conversation_id,
            len(message),
        )
        conversation = await self.conversation_service.prepare_conversation(
            user_key=user_key,
            message=message,
            conversation_id=conversation_id,
        )
        prepared_conversation_id = conversation.id
        prepared_conversation = conversation.to_dict()
        logger.info(
            "Runtime stream conversation prepared: mode=%s user_key=%s conversation_id=%s",
            self.mode,
            user_key,
            prepared_conversation_id,
        )
        await self.conversation_service.save_user_message(prepared_conversation_id, message)
        logger.info(
            "Runtime stream user message saved: mode=%s conversation_id=%s",
            self.mode,
            prepared_conversation_id,
        )
        yield {
            "type": "conversation",
            "conversation_id": prepared_conversation_id,
            "conversation": prepared_conversation,
            "mode": self.mode,
        }

        selection = await self.selection_service.get_or_default(user_key)
        resources = await self.resource_service.resolve_for_selection(selection)
        logger.info(
            "Runtime stream resources resolved: mode=%s conversation_id=%s mcps=%s skills=%s subagents=%s tools=%s",
            self.mode,
            prepared_conversation_id,
            len(resources.get("mcps", [])),
            len(resources.get("skills", [])),
            len(resources.get("subagents", [])),
            len(resources.get("tools", [])),
        )
        result = await self._generate_result(
            user_key=user_key,
            message=message,
            conversation_id=prepared_conversation_id,
            selection=selection,
            resources=resources,
        )

        for token in self._chunk_answer(result.answer):
            yield {"type": "token", "content": token, "mode": self.mode}
            await asyncio.sleep(0.01)

        await self.conversation_service.save_assistant_message(
            conversation_id=prepared_conversation_id,
            content=result.answer,
            metadata=result.metadata,
        )
        logger.info(
            "Runtime stream assistant message saved: mode=%s conversation_id=%s answer_chars=%s",
            self.mode,
            prepared_conversation_id,
            len(result.answer),
        )
        response = await self.conversation_service.build_chat_response(
            conversation_id=prepared_conversation_id,
            user_key=user_key,
            answer=result.answer,
            selection=selection,
            resources=resources,
        )
        logger.info("Runtime stream done event ready: mode=%s conversation_id=%s", self.mode, prepared_conversation_id)
        yield {"type": "done", **self._build_response(response, result)}

    @abstractmethod
    async def _generate_result(
        self,
        *,
        user_key: str,
        message: str,
        conversation_id: int,
        selection: dict,
        resources: dict[str, list[dict]],
    ) -> RuntimeResult:
        """Generate the mode-specific assistant answer."""

    def _build_response(self, response: dict, result: RuntimeResult) -> dict:
        response["mode"] = self.mode
        response.update(result.response_extra)
        return response

    def _chunk_answer(self, answer: str) -> list[str]:
        if not answer:
            return [""]
        return [answer[index : index + 4] for index in range(0, len(answer), 4)]
