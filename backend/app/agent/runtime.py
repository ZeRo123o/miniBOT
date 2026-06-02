import asyncio
from collections.abc import AsyncIterator
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import AgentContext
from app.core.config import get_settings
from app.graph.builder import build_chat_agent
from app.llm.factory import CHAT_MODEL
from app.services import ConversationService, ResourceService, SelectionService


class AgentRuntime:
    MISSING_OPENAI_API_KEY_ERROR = "MINIBOT_OPENAI_API_KEY is required for OpenAI-compatible provider."
    MISSING_OPENAI_API_KEY_REPLY = (
        "当前未配置模型 API Key，暂时无法调用真实大模型。\n\n"
        "请在后端 .env 中配置 MINIBOT_OPENAI_API_KEY，或将模型 provider 切换为 mock 后重试。"
    )

    def __init__(self, db: AsyncSession):
        """初始化一次请求内复用的业务服务。"""
        self.conversation_service = ConversationService(db)
        self.selection_service = SelectionService(db)
        self.resource_service = ResourceService(db)

    async def run(self, *, user_key: str, message: str, conversation_id: int | None = None) -> dict:
        """执行完整聊天流程，并把具体业务操作委托给 service 层。"""
        conversation = await self.conversation_service.prepare_conversation(
            user_key=user_key,
            message=message,
            conversation_id=conversation_id,
        )
        await self.conversation_service.save_user_message(conversation.id, message)

        graph_messages = await self.conversation_service.load_langchain_messages(conversation.id)
        selection = await self.selection_service.get_or_default(user_key)
        resources = await self.resource_service.resolve_for_selection(selection)
        context = self._build_context(
            user_key=user_key,
            conversation_id=conversation.id,
            resources=resources,
        )

        agent = build_chat_agent(context)
        try:
            result = await agent.ainvoke(
                {"messages": graph_messages},
                context=context,
            )
            answer = result["messages"][-1].content
            assistant_metadata = {"resources": resources, "tool_events": context.tool_events}
        except ValueError as error:
            if str(error) != self.MISSING_OPENAI_API_KEY_ERROR:
                raise
            answer = self.MISSING_OPENAI_API_KEY_REPLY
            assistant_metadata = {
                "resources": resources,
                "tool_events": context.tool_events,
                "error": "missing_openai_api_key",
            }
        await self.conversation_service.save_assistant_message(
            conversation_id=conversation.id,
            content=answer,
            metadata=assistant_metadata,
        )
        return await self.conversation_service.build_chat_response(
            conversation_id=conversation.id,
            user_key=user_key,
            answer=answer,
            selection=selection,
            resources=resources,
        )

    async def run_stream(
        self,
        *,
        user_key: str,
        message: str,
        conversation_id: int | None = None,
    ) -> AsyncIterator[dict]:
        """Stream chat events for the frontend while preserving persisted conversation history."""
        conversation = await self.conversation_service.prepare_conversation(
            user_key=user_key,
            message=message,
            conversation_id=conversation_id,
        )
        prepared_conversation_id = conversation.id
        prepared_conversation = conversation.to_dict()
        await self.conversation_service.save_user_message(prepared_conversation_id, message)
        yield {
            "type": "conversation",
            "conversation_id": prepared_conversation_id,
            "conversation": prepared_conversation,
        }

        graph_messages = await self.conversation_service.load_langchain_messages(prepared_conversation_id)
        selection = await self.selection_service.get_or_default(user_key)
        resources = await self.resource_service.resolve_for_selection(selection)
        context = self._build_context(
            user_key=user_key,
            conversation_id=prepared_conversation_id,
            resources=resources,
        )

        agent = build_chat_agent(context)
        try:
            result = await agent.ainvoke(
                {"messages": graph_messages},
                context=context,
            )
            answer = result["messages"][-1].content
            assistant_metadata = {"resources": resources, "tool_events": context.tool_events}
        except ValueError as error:
            if str(error) != self.MISSING_OPENAI_API_KEY_ERROR:
                raise
            answer = self.MISSING_OPENAI_API_KEY_REPLY
            assistant_metadata = {
                "resources": resources,
                "tool_events": context.tool_events,
                "error": "missing_openai_api_key",
            }

        for token in self._chunk_answer(answer):
            yield {"type": "token", "content": token}
            await asyncio.sleep(0.01)

        await self.conversation_service.save_assistant_message(
            conversation_id=prepared_conversation_id,
            content=answer,
            metadata=assistant_metadata,
        )
        response = await self.conversation_service.build_chat_response(
            conversation_id=prepared_conversation_id,
            user_key=user_key,
            answer=answer,
            selection=selection,
            resources=resources,
        )
        yield {"type": "done", **response}

    def _build_context(
        self,
        *,
        user_key: str,
        conversation_id: int,
        resources: dict[str, list[dict]],
    ) -> AgentContext:
        """把数据库资源和运行时配置整理成 AgentContext。"""
        settings = get_settings()
        return AgentContext(
            user_key=user_key,
            conversation_id=conversation_id,
            system_prompt=settings.default_system_prompt,
            model_use=CHAT_MODEL,
            current_datetime=self._current_datetime(settings.runtime_timezone),
            timezone=settings.runtime_timezone,
            mcps=resources["mcps"],
            skills=resources["skills"],
            subagents=resources["subagents"],
            tools=resources["tools"],
            max_tool_calls=settings.runtime_tool_call_limit,
            summary_context_window_tokens=settings.summary_context_window_tokens,
            summary_trigger_ratio=settings.summary_trigger_ratio,
            summary_trigger_tokens=settings.summary_trigger_tokens,
            summary_keep_messages=settings.summary_keep_messages,
            summary_max_chars=settings.summary_max_chars,
        )

    def _current_datetime(self, timezone_name: str) -> str:
        """根据配置时区生成当前时间字符串，供 prompt 注入使用。"""
        try:
            current_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            current_timezone = timezone_utc8()
        return datetime.now(current_timezone).strftime("%Y-%m-%d %H:%M:%S")

    def _chunk_answer(self, answer: str) -> list[str]:
        """Split a completed answer into small pieces for a stable SSE typing experience."""
        if not answer:
            return [""]
        return [answer[index : index + 4] for index in range(0, len(answer), 4)]


def timezone_utc8() -> timezone:
    """在 Windows 缺少 IANA 时区数据库时，提供 Asia/Shanghai 等价的 UTC+8 时区。"""
    return timezone(timedelta(hours=8), name="Asia/Shanghai")
