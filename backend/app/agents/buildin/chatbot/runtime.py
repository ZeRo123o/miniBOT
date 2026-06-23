import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from langchain_core.messages import AIMessageChunk

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.buildin.chatbot.graph import build_chat_agent
from app.agents.middlewares.subagent_middleware import create_parent_run, finish_run, make_parent_thread_id
from app.agents.runtime_base import BaseChatRuntime, RuntimeResult
from app.agents.toolkits.governance import serialize_tool_calls
from app.core.config import get_settings
from app.llm.factory import CHAT_MODEL
from app.llm.chat_model import ModelRequestTimeoutError
from app.services.attachment_service import build_attachment_state_files

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
        uploads: list[dict] | None = None,
        event_sink: Callable[[dict], None] | None = None,
    ) -> RuntimeResult:
        graph_messages = await self.conversation_service.load_langchain_messages(conversation_id)
        if hasattr(self.conversation_service, "load_attachment_state"):
            state_uploads, state_files = await self.conversation_service.load_attachment_state(conversation_id)
        else:
            state_uploads = list(uploads or [])
            state_files = build_attachment_state_files(state_uploads)
        thread_id = make_parent_thread_id(conversation_id)
        parent_run = await create_parent_run(
            user_id=user_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            message=message,
        )
        context = self._build_context(
            user_id=user_id,
            conversation_id=conversation_id,
            selection=selection,
            resources=resources,
            thread_id=thread_id,
            run_id=str(parent_run["id"]),
        )
        context.runtime_event_sink = event_sink
        try:
            agent = await build_chat_agent(context)
            checkpoint_config = {"configurable": {"thread_id": thread_id}}
            checkpoint_state = await agent.aget_state(checkpoint_config)
            if checkpoint_state.values.get("messages"):
                # The checkpoint already has this thread's history; only append the new user message.
                graph_messages = graph_messages[-1:]
            result = await agent.ainvoke(
                {"messages": graph_messages, "uploads": state_uploads, "files": state_files},
                config=checkpoint_config,
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
                "tool_calls": serialize_tool_calls(context.tool_events),
                "subagent_runs": result.get("subagent_runs") or [],
                "artifacts": result.get("artifacts") or [],
                "activated_skills": activated_skills,
            }
            await finish_run(
                str(parent_run["id"]),
                status="completed",
                result_payload={
                    "content": answer,
                    "subagent_runs": assistant_metadata["subagent_runs"],
                },
            )
        except ValueError as error:
            if str(error) != self.MISSING_OPENAI_API_KEY_ERROR:
                await finish_run(str(parent_run["id"]), status="failed", error=error)
                raise
            answer = self.MISSING_OPENAI_API_KEY_REPLY
            assistant_metadata = {
                "resources": resources,
                "tool_calls": serialize_tool_calls(context.tool_events),
                "workflow": "agent",
                "error": "missing_openai_api_key",
            }
            await finish_run(str(parent_run["id"]), status="failed", error=error)
        except ModelRequestTimeoutError:
            logger.warning(
                "Agent model request timed out: user_id=%s conversation_id=%s",
                user_id,
                conversation_id,
            )
            answer = self.MODEL_TIMEOUT_REPLY
            assistant_metadata = {
                "resources": resources,
                "tool_calls": serialize_tool_calls(context.tool_events),
                "workflow": "agent",
                "error": "model_timeout",
            }
            await finish_run(str(parent_run["id"]), status="failed")
        except Exception as error:
            await finish_run(str(parent_run["id"]), status="failed", error=error)
            raise
        return RuntimeResult(
            answer=answer,
            metadata=assistant_metadata,
            response_extra={
                "citations": self._collect_citations(context.tool_events),
                "artifacts": assistant_metadata.get("artifacts") or [],
                "subagent_runs": assistant_metadata.get("subagent_runs") or [],
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
        thread_id: str,
        run_id: str,
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
            thread_id=thread_id,
            run_id=run_id,
            summary_trigger_tokens=settings.summary_trigger_tokens,
            summary_trigger_messages=settings.summary_trigger_messages,
            summary_keep_messages=settings.summary_keep_messages,
            summary_trim_tokens_to_summarize=settings.summary_trim_tokens_to_summarize,
            summary_offload_threshold_tokens=settings.summary_offload_threshold_tokens,
            summary_offload_preview_lines=settings.summary_offload_preview_lines,
            summary_max_retention_ratio=settings.summary_max_retention_ratio,
        )

    async def _generate_stream_result(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int,
        selection: dict,
        resources: dict[str, list[dict]],
        uploads: list[dict],
    ) -> AsyncIterator[dict | RuntimeResult]:
        """Forward true model chunks and runtime events while the parent graph is running."""
        event_queue: asyncio.Queue[dict] = asyncio.Queue()
        agent_task = asyncio.create_task(
            self._stream_agent_response(
                user_id=user_id,
                message=message,
                conversation_id=conversation_id,
                selection=selection,
                resources=resources,
                uploads=uploads,
                event_sink=event_queue.put_nowait,
            )
        )
        while not agent_task.done():
            try:
                yield await asyncio.wait_for(event_queue.get(), timeout=0.1)
            except TimeoutError:
                continue
        while not event_queue.empty():
            yield event_queue.get_nowait()
        yield await agent_task

    async def _stream_agent_response(
        self,
        *,
        user_id: str,
        message: str,
        conversation_id: int,
        selection: dict,
        resources: dict[str, list[dict]],
        uploads: list[dict],
        event_sink: Callable[[dict], None],
    ) -> RuntimeResult:
        """Run `astream` and persist the final checkpoint state after true token streaming."""
        graph_messages = await self.conversation_service.load_langchain_messages(conversation_id)
        if hasattr(self.conversation_service, "load_attachment_state"):
            state_uploads, state_files = await self.conversation_service.load_attachment_state(conversation_id)
        else:
            state_uploads = list(uploads)
            state_files = build_attachment_state_files(state_uploads)
        thread_id = make_parent_thread_id(conversation_id)
        parent_run = await create_parent_run(
            user_id=user_id,
            conversation_id=conversation_id,
            thread_id=thread_id,
            message=message,
        )
        context = self._build_context(
            user_id=user_id,
            conversation_id=conversation_id,
            selection=selection,
            resources=resources,
            thread_id=thread_id,
            run_id=str(parent_run["id"]),
        )
        context.runtime_event_sink = event_sink
        try:
            agent = await build_chat_agent(context)
            checkpoint_config = {"configurable": {"thread_id": thread_id}}
            checkpoint_state = await agent.aget_state(checkpoint_config)
            if checkpoint_state.values.get("messages"):
                # The checkpointer owns prior turns, so this invocation carries only the new input.
                graph_messages = graph_messages[-1:]

            last_values: dict = {}
            async for mode, payload in agent.astream(
                {"messages": graph_messages, "uploads": state_uploads, "files": state_files},
                config=checkpoint_config,
                context=context,
                stream_mode=["messages", "values"],
            ):
                if mode == "values" and isinstance(payload, dict):
                    last_values = payload
                    continue
                if mode == "messages":
                    self._forward_primary_token(context, payload)

            # Like Yuxi, the checkpoint is authoritative for the completed response.
            final_state = await agent.aget_state(checkpoint_config)
            result = final_state.values if final_state and final_state.values else last_values
            answer = str(getattr(result.get("messages", [])[-1], "content", "")) if result.get("messages") else ""
            assistant_metadata = {
                "workflow": "agent",
                "resources": resources,
                "tool_calls": serialize_tool_calls(context.tool_events),
                "subagent_runs": result.get("subagent_runs") or [],
                "artifacts": result.get("artifacts") or [],
                "activated_skills": self._activated_skills_from_result(result),
            }
            await finish_run(
                str(parent_run["id"]),
                status="completed",
                result_payload={
                    "content": answer,
                    "subagent_runs": assistant_metadata["subagent_runs"],
                },
            )
        except ValueError as error:
            if str(error) != self.MISSING_OPENAI_API_KEY_ERROR:
                await finish_run(str(parent_run["id"]), status="failed", error=error)
                raise
            answer = self.MISSING_OPENAI_API_KEY_REPLY
            event_sink({"type": "token", "content": answer})
            assistant_metadata = {
                "resources": resources,
                "tool_calls": serialize_tool_calls(context.tool_events),
                "workflow": "agent",
                "error": "missing_openai_api_key",
            }
            await finish_run(str(parent_run["id"]), status="failed", error=error)
        except ModelRequestTimeoutError:
            logger.warning("Agent model request timed out: user_id=%s conversation_id=%s", user_id, conversation_id)
            answer = self.MODEL_TIMEOUT_REPLY
            event_sink({"type": "token", "content": answer})
            assistant_metadata = {
                "resources": resources,
                "tool_calls": serialize_tool_calls(context.tool_events),
                "workflow": "agent",
                "error": "model_timeout",
            }
            await finish_run(str(parent_run["id"]), status="failed")
        except Exception as error:
            await finish_run(str(parent_run["id"]), status="failed", error=error)
            raise
        return RuntimeResult(
            answer=answer,
            metadata=assistant_metadata,
            response_extra={
                "citations": self._collect_citations(context.tool_events),
                "artifacts": assistant_metadata.get("artifacts") or [],
                "subagent_runs": assistant_metadata.get("subagent_runs") or [],
            },
        )

    @staticmethod
    def _forward_primary_token(context: AgentContext, payload: object) -> None:
        """Only forward primary graph model text; subagent text has its own SSE event."""
        if context.active_subagent_run_count:
            return
        if not isinstance(payload, tuple) or len(payload) != 2:
            return
        message, metadata = payload
        if (
            not isinstance(message, AIMessageChunk)
            or not isinstance(metadata, dict)
            or metadata.get("langgraph_node") != "model"
            or not isinstance(message.content, str)
            or not message.content
        ):
            return
        if callable(context.runtime_event_sink):
            context.runtime_event_sink({"type": "token", "content": message.content})


    def _current_datetime(self, timezone_name: str) -> str:
        """根据配置时区生成当前时间字符串，供 prompt 注入使用。"""
        try:
            current_timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            current_timezone = timezone_utc8()
        return datetime.now(current_timezone).strftime("%Y-%m-%d %H:%M:%S")

def timezone_utc8() -> timezone:
    """在 Windows 缺少 IANA 时区数据库时，提供 Asia/Shanghai 等价的 UTC+8 时区。"""
    return timezone(timedelta(hours=8), name="Asia/Shanghai")
