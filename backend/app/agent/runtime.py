from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.context import AgentContext
from app.core.config import get_settings
from app.db.models import Conversation, ConversationMessage
from app.db.repositories import ConversationMessageRepository, ConversationRepository, UserSelectionRepository
from app.graph.builder import build_chat_agent
from app.llm.factory import CHAT_MODEL
from app.plugins.registry import list_enabled_resources, resolve_resources_by_name


class AgentRuntime:
    def __init__(self, db: AsyncSession):
        """初始化一次请求内复用的仓储对象。"""
        self.db = db
        self.conversation_repo = ConversationRepository(db)
        self.message_repo = ConversationMessageRepository(db)
        self.selection_repo = UserSelectionRepository(db)

    async def run(self, *, user_key: str, message: str, conversation_id: int | None = None) -> dict:
        """执行完整聊天流程：保存用户消息、构建上下文、调用 agent 并保存回复。"""
        conversation = await self._prepare_conversation(
            user_key=user_key,
            message=message,
            conversation_id=conversation_id,
        )
        await self.message_repo.create(conversation.id, role="user", content=message)

        graph_messages = await self._load_graph_messages(conversation.id)
        selection = await self._load_selection(user_key)
        resources = await self._resolve_resources(selection)
        context = self._build_context(
            user_key=user_key,
            conversation_id=conversation.id,
            resources=resources,
        )

        agent = build_chat_agent(context)
        result = await agent.ainvoke(
            {"messages": graph_messages},
            context=context,
        )

        answer = result["messages"][-1].content
        await self.message_repo.create(
            conversation.id,
            role="assistant",
            content=answer,
            metadata={"resources": resources, "tool_events": context.tool_events},
        )
        return await self._build_response(
            conversation_id=conversation.id,
            user_key=user_key,
            answer=answer,
            selection=selection,
            resources=resources,
        )

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
        )

    def _current_datetime(self, timezone_name: str) -> str:
        """根据配置时区生成当前时间字符串，供 prompt 注入使用。"""
        try:
            current_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            current_timezone = timezone_utc8()
        return datetime.now(current_timezone).strftime("%Y-%m-%d %H:%M:%S")

    async def _prepare_conversation(
        self,
        *,
        user_key: str,
        message: str,
        conversation_id: int | None,
    ) -> Conversation:
        """创建或校验会话，并在空会话首次发送消息时自动命名。"""
        title = message[:24] or "新对话"
        if conversation_id is None:
            return await self.conversation_repo.create(user_key=user_key, title=title)

        conversation = await self.conversation_repo.get(conversation_id, user_key=user_key)
        if conversation is None:
            raise ValueError("Conversation not found.")

        existing_messages = await self.message_repo.list(conversation.id)
        if not existing_messages and conversation.title == "新对话":
            conversation = await self.conversation_repo.update(conversation, title=title)
        return conversation

    async def _load_graph_messages(self, conversation_id: int) -> list[BaseMessage]:
        """读取会话历史消息，并转换为 LangChain 消息格式。"""
        persisted_messages = await self.message_repo.list(conversation_id)
        return [
            converted
            for message in persisted_messages
            if (converted := self._to_langchain_message(message)) is not None
        ]

    def _to_langchain_message(self, message: ConversationMessage) -> BaseMessage | None:
        """把数据库消息转换成模型可消费的 LangChain message。"""
        if message.role == "user":
            return HumanMessage(content=message.content)
        if message.role == "assistant":
            return AIMessage(content=message.content)
        return None

    async def _load_selection(self, user_key: str) -> dict:
        """读取用户资源选择；未配置时返回空选择。"""
        selection_item = await self.selection_repo.get(user_key)
        if selection_item:
            return selection_item.to_dict()
        return {"user_key": user_key, "mcps": [], "skills": [], "subagents": []}

    async def _resolve_resources(self, selection: dict) -> dict[str, list[dict]]:
        """解析 MCP、Skill、Subagent，并读取所有启用的运行时工具。"""
        return {
            "mcps": await resolve_resources_by_name(self.db, kind="mcp", names=selection["mcps"]),
            "skills": await resolve_resources_by_name(self.db, kind="skill", names=selection["skills"]),
            "subagents": await resolve_resources_by_name(self.db, kind="subagent", names=selection["subagents"]),
            "tools": await list_enabled_resources(self.db, kind="tool"),
        }

    async def _build_response(
        self,
        *,
        conversation_id: int,
        user_key: str,
        answer: str,
        selection: dict,
        resources: dict[str, list[dict]],
    ) -> dict:
        """构造返回给前端的聊天响应。"""
        messages = await self.message_repo.list(conversation_id)
        conversation = await self.conversation_repo.get(conversation_id, user_key=user_key)
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


def timezone_utc8() -> timezone:
    """在 Windows 缺少 IANA 时区数据库时，提供 Asia/Shanghai 等价的 UTC+8 时区。"""
    return timezone(timedelta(hours=8), name="Asia/Shanghai")
