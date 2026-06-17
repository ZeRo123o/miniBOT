import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.buildin.chatbot.graph import build_chat_agent
from app.agents.runtime_base import BaseChatRuntime, RuntimeResult
from app.core.config import get_settings
from app.llm.factory import CHAT_MODEL
from app.llm.chat_model import ModelRequestTimeoutError

logger = logging.getLogger(__name__)


class AgentRuntime(BaseChatRuntime):
    MISSING_OPENAI_API_KEY_ERROR = "MINIBOT_OPENAI_API_KEY is required for OpenAI-compatible provider."
    MISSING_OPENAI_API_KEY_REPLY = (
        "当前未配置模型 API Key，暂时无法调用真实大模型。\n\n"
        "请在后端 .env 中配置 MINIBOT_OPENAI_API_KEY，或将模型 provider 切换为 mock 后重试。"
    )
    MODEL_TIMEOUT_REPLY = (
        "模型服务响应超时，本次请求没有完成。请稍后重试；"
        "如果任务较复杂，可以适当提高 MINIBOT_OPENAI_TIMEOUT_SECONDS。"
    )

    async def _generate_result(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int,
        selection: dict,
        resources: dict[str, list[dict]],
    ) -> RuntimeResult:
        graph_messages = await self.conversation_service.load_langchain_messages(conversation_id)
        context = self._build_context(
            user_id=user_id,
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
            activated_skills = self._activated_skills_from_result(result)
            logger.info(
                "Agent Skill run summary: user_id=%s conversation_id=%s "
                "selected_skills=%s activated_skills=%s",
                user_id,
                conversation_id,
                context.skills,
                activated_skills,
            )
            assistant_metadata = {
                "workflow": "agent",
                "resources": resources,
                "tool_events": context.tool_events,
                "artifacts": result.get("artifacts") or [],
                "activated_skills": activated_skills,
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
        except ModelRequestTimeoutError:
            logger.warning(
                "Agent model request timed out: user_id=%s conversation_id=%s",
                user_id,
                conversation_id,
            )
            answer = self.MODEL_TIMEOUT_REPLY
            assistant_metadata = {
                "resources": resources,
                "tool_events": context.tool_events,
                "workflow": "agent",
                "error": "model_timeout",
            }
        return RuntimeResult(
            answer=answer,
            metadata=assistant_metadata,
            response_extra={
                "citations": self._collect_citations(context.tool_events),
                "artifacts": assistant_metadata.get("artifacts") or [],
            },
        )

    @staticmethod
    def _activated_skills_from_result(result: dict) -> list[str]:
        """Return unique Skill slugs activated during this agent run."""
        activated = result.get("activated_skills") or []
        if not isinstance(activated, list):
            return []
        return list(dict.fromkeys(
            slug.strip()
            for slug in activated
            if isinstance(slug, str) and slug.strip()
        ))

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
        user_id: str,
        conversation_id: int,
        selection: dict,
        resources: dict[str, list[dict]],
    ) -> AgentContext:
        """把数据库资源和运行时配置整理成 AgentContext。"""
        settings = get_settings()
        knowledge_base_ids = selection.get("knowledge_base_ids", []) or []
        logger.info(
            "Knowledge bases enabled for agent run: user_id=%s conversation_id=%s knowledge_base_ids=%s",
            user_id,
            conversation_id,
            knowledge_base_ids,
        )
        skill_slugs = [
            str(item.get("slug") or "")
            for item in resources["skills"]
            if item.get("slug")
        ]
        logger.info(
            "Agent runtime resources: user_id=%s conversation_id=%s skills=%s tools=%s mcps=%s",
            user_id,
            conversation_id,
            skill_slugs,
            [item.get("name") for item in resources["tools"]],
            [item.get("name") for item in resources["mcps"]],
        )
        return AgentContext(
            user_id=user_id,
            conversation_id=conversation_id,
            system_prompt=settings.default_system_prompt,
            model_use=CHAT_MODEL,
            current_datetime=self._current_datetime(settings.runtime_timezone),
            timezone=settings.runtime_timezone,
            mcps=resources["mcps"],
            skills=skill_slugs,
            tools=resources["tools"],
            knowledge_base_ids=knowledge_base_ids,
            max_tool_calls=settings.runtime_tool_call_limit,
            summary_trigger_tokens=settings.summary_trigger_tokens,
            summary_trigger_messages=settings.summary_trigger_messages,
            summary_keep_messages=settings.summary_keep_messages,
            summary_trim_tokens_to_summarize=settings.summary_trim_tokens_to_summarize,
            summary_offload_threshold_tokens=settings.summary_offload_threshold_tokens,
            summary_offload_preview_lines=settings.summary_offload_preview_lines,
            summary_max_retention_ratio=settings.summary_max_retention_ratio,
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
