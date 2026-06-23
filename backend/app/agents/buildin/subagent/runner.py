from __future__ import annotations

from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.middlewares.subagent_middleware import SubAgentContext, SubAgentProfile
from app.agents.buildin.subagent.graph import build_subagent_agent
from app.agents.toolkits.governance import emit_runtime_event


def _final_assistant_text(messages: list[Any]) -> str:
    """从末尾回溯，提取最后一条包含文本的子智能体回答。"""
    for message in reversed(messages):
        if isinstance(message, AIMessage):
            text = message.text.rstrip() if message.text else ""
            if text:
                return text
    return "子智能体已完成任务，但没有返回文本结果。"


class SubAgentRunner:
    """Create a child agent with an isolated context and return its final result."""

    async def run(
        self,
        *,
        parent_context: AgentContext,
        profile: SubAgentProfile,
        prompt: str,
        expected_output: str = "",
        uploads: list[dict] | None = None,
        files: dict | None = None,
        child_thread_id: str = "",
        child_run_id: str = "",
        parent_tool_call_id: str = "",
    ) -> dict[str, Any]:
        child_context = self._build_child_context(
            parent_context,
            profile,
            child_thread_id,
            child_run_id,
            parent_tool_call_id,
        )
        child_agent = await build_subagent_agent(child_context)
        child_input = {
            "messages": [HumanMessage(content=self._build_task_message(prompt, expected_output))],
            "uploads": uploads or [],
            "files": files or {},
        }
        config = {"configurable": {"thread_id": child_thread_id}}
        result: dict[str, Any] | None = None
        async for mode, chunk in child_agent.astream(
            child_input,
            config=config,
            context=child_context,
            stream_mode=["messages", "values"],
        ):
            if mode == "values" and isinstance(chunk, dict):
                result = chunk
            elif mode == "messages":
                self._emit_token(child_context, chunk)
        if result is None:
            result = (await child_agent.aget_state(config)).values
        return {
            "content": _final_assistant_text(result.get("messages") or []),
            "artifacts": result.get("artifacts") or [],
            "tool_events": child_context.tool_events,
        }

    def _build_child_context(
        self,
        parent_context: AgentContext,
        profile: SubAgentProfile,
        child_thread_id: str,
        child_run_id: str,
        parent_tool_call_id: str,
    ) -> SubAgentContext:
        """Build a minimal child context without inheriting parent messages or prompt."""
        return SubAgentContext(
            user_id=parent_context.user_id,
            conversation_id=parent_context.conversation_id,
            subagent_type=profile.name,
            thread_id=child_thread_id,
            parent_thread_id=parent_context.thread_id,
            run_id=child_run_id,
            parent_tool_call_id=parent_tool_call_id,
            runtime_event_sink=parent_context.runtime_event_sink,
            system_prompt=profile.system_prompt,
            model_use=profile.model_use or parent_context.model_use,
            current_datetime=parent_context.current_datetime,
            timezone=parent_context.timezone,
            skills=self._authorized_skills(parent_context, profile),
            tools=self._authorized_tools(parent_context, profile),
            knowledge_base_ids=list(parent_context.knowledge_base_ids),
            max_tool_calls=profile.max_tool_calls,
            sandbox_id=parent_context.sandbox_id,
            allow_subagents=False,
            subagent_depth=parent_context.subagent_depth + 1,
            summary_trigger_tokens=parent_context.summary_trigger_tokens,
            summary_trigger_messages=parent_context.summary_trigger_messages,
            summary_keep_messages=parent_context.summary_keep_messages,
            summary_trim_tokens_to_summarize=parent_context.summary_trim_tokens_to_summarize,
            summary_offload_threshold_tokens=parent_context.summary_offload_threshold_tokens,
            summary_offload_preview_lines=parent_context.summary_offload_preview_lines,
            summary_max_retention_ratio=parent_context.summary_max_retention_ratio,
        )

    def _authorized_tools(
        self,
        parent_context: AgentContext,
        profile: SubAgentProfile,
    ) -> list[dict]:
        requested = {name for name in profile.tool_names if name != "task"}
        return [
            resource
            for resource in parent_context.tools
            if str(resource.get("name") or "") in requested
        ]

    def _authorized_skills(
        self,
        parent_context: AgentContext,
        profile: SubAgentProfile,
    ) -> list[str]:
        parent_skills = set(parent_context.skills or [])
        return [slug for slug in profile.skill_slugs if slug in parent_skills]

    @staticmethod
    def _emit_token(context: SubAgentContext, chunk: Any) -> None:
        """Forward only model text chunks; tool protocol chunks stay in the task card activity feed."""
        if not isinstance(chunk, tuple) or len(chunk) != 2:
            return
        message, metadata = chunk
        if not isinstance(message, AIMessageChunk) or not isinstance(metadata, dict):
            return
        if metadata.get("langgraph_node") != "model" or not isinstance(message.content, str):
            return
        if message.content:
            emit_runtime_event(
                context,
                {
                    "type": "subagent_token",
                    "child_thread_id": context.thread_id,
                    "subagent_type": context.subagent_type,
                    "tool_call_id": context.parent_tool_call_id,
                    "run_id": context.run_id,
                    "content": message.content,
                },
            )

    def _build_task_message(
        self,
        prompt: str,
        expected_output: str = "",
    ) -> str:
        lines = [
            "你正在作为子智能体执行主智能体委派的独立任务。",
            "",
            "任务：",
            prompt.strip(),
        ]
        if expected_output.strip():
            lines.extend(["", "期望输出：", expected_output.strip()])
        lines.extend(
            [
                "",
                "请只返回完成该子任务所需的结论、依据、关键中间发现和必要的后续建议。",
            ]
        )
        return "\n".join(lines)
