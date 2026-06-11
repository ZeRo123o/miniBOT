import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.buildin.chatbot.graph import build_chat_agent
from app.agents.runtime_base import BaseChatRuntime, RuntimeResult
from app.core.config import get_settings
from app.llm.factory import CHAT_MODEL

logger = logging.getLogger(__name__)


class AgentRuntime(BaseChatRuntime):
    MISSING_OPENAI_API_KEY_ERROR = "MINIBOT_OPENAI_API_KEY is required for OpenAI-compatible provider."
    MISSING_OPENAI_API_KEY_REPLY = (
        "当前未配置模型 API Key，暂时无法调用真实大模型。\n\n"
        "请在后端 .env 中配置 MINIBOT_OPENAI_API_KEY，或将模型 provider 切换为 mock 后重试。"
    )

    async def _generate_result(
        self,
        *,
        user_key: str,
        message: str,
        conversation_id: int,
        selection: dict,
        resources: dict[str, list[dict]],
    ) -> RuntimeResult:
        graph_messages = await self.conversation_service.load_langchain_messages(conversation_id)
        context = self._build_context(
            user_key=user_key,
            conversation_id=conversation_id,
            selection=selection,
            resources=resources,
        )
        agent = build_chat_agent(context)
        try:
            result = await agent.ainvoke(
                {"messages": graph_messages},
                context=context,
            )
            answer = result["messages"][-1].content
            assistant_metadata = {
                "workflow": "agent",
                "resources": resources,
                "tool_events": context.tool_events,
                "artifacts": result.get("artifacts") or [],
            }
        except ValueError as error:
            if str(error) != self.MISSING_OPENAI_API_KEY_ERROR:
                raise
            answer = self.MISSING_OPENAI_API_KEY_REPLY
            assistant_metadata = {
                "resources": resources,
                "tool_events": context.tool_events,
                "workflow": "agent",
                "error": "missing_openai_api_key",
            }
        return RuntimeResult(
            answer=answer,
            metadata=assistant_metadata,
            response_extra={
                "citations": self._collect_citations(context.tool_events),
                "artifacts": assistant_metadata.get("artifacts") or [],
            },
        )

    def _collect_citations(self, tool_events: list[dict]) -> list[dict]:
        """Return unique knowledge chunks actually retrieved during this agent run."""
        citations = []
        seen = set()
        for event in tool_events:
            if event.get("tool_name") != "query_kb":
                continue
            for item in event.get("results") or []:
                citation_id = (item.get("metadata") or {}).get("citation_id")
                if not citation_id or citation_id in seen:
                    continue
                seen.add(citation_id)
                citations.append(item)
        return citations

    def _build_context(
        self,
        *,
        user_key: str,
        conversation_id: int,
        selection: dict,
        resources: dict[str, list[dict]],
    ) -> AgentContext:
        """把数据库资源和运行时配置整理成 AgentContext。"""
        settings = get_settings()
        knowledge_base_ids = selection.get("knowledge_base_ids", []) or []
        logger.info(
            "Knowledge bases enabled for agent run: user_key=%s conversation_id=%s knowledge_base_ids=%s",
            user_key,
            conversation_id,
            knowledge_base_ids,
        )
        return AgentContext(
            user_key=user_key,
            conversation_id=conversation_id,
            system_prompt=settings.default_system_prompt,
            model_use=CHAT_MODEL,
            current_datetime=self._current_datetime(settings.runtime_timezone),
            timezone=settings.runtime_timezone,
            mcps=resources["mcps"],
            skills=resources["skills"],
            tools=resources["tools"],
            knowledge_base_ids=knowledge_base_ids,
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
