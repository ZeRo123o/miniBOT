from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Annotated, Any

from app.agents.context import BaseAgentContext
from app.agents.buildin.chatbot.prompt import DEFAULT_SYSTEM_PROMPT


@dataclass(kw_only=True)
class AgentContext(BaseAgentContext):
    system_prompt: Annotated[str, {"__template_metadata__": {"kind": "prompt"}}] = field(
        default=DEFAULT_SYSTEM_PROMPT,
        metadata={
            "name": "系统提示词",
            "description": "智能助手的基础角色和行为提示词。",
        },
    )
    knowledge_base_ids: Annotated[list[int], {"__template_metadata__": {"kind": "knowledges"}}] = field(
        default_factory=list,
        metadata={
            "name": "知识库",
            "description": "当前会话启用的知识库 ID 列表。",
            "type": "list",
        },
    )
    tool_events: list[dict] = field(default_factory=list)
    runtime_event_sink: Callable[[dict[str, Any]], None] | None = field(
        default=None,
        repr=False,
        metadata={"configurable": False, "hide": True},
    )
    thread_id: str = ""
    parent_thread_id: str | None = None
    run_id: str = ""
    allow_subagents: bool = True
    subagent_depth: int = 0
    max_subagent_tasks_per_run: int = 3
    subagent_task_count: int = 0
    active_subagent_run_count: int = 0
    subagent_prompt_max_chars: int = 12000
    subagent_result_max_chars: int = 12000
    sandbox_id: str = ""
    summary: str = ""
    summary_trigger_tokens: int = 90000
    summary_trigger_messages: int = 0
    summary_keep_messages: int = 20
    summary_trim_tokens_to_summarize: int | None = 4000
    summary_max_retention_ratio: float = 0.6
    summary_prompt: Annotated[str, {"__template_metadata__": {"kind": "prompt"}}] = ""
    tool_output_budget_enabled: bool = True
    tool_output_offload_threshold_chars: int = 16000
    tool_output_preview_head_chars: int = 4000
    tool_output_preview_tail_chars: int = 2000
    tool_output_fallback_max_chars: int = 8000
