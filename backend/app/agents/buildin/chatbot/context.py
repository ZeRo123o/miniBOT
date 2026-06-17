from dataclasses import dataclass, field
from typing import Annotated

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
    sandbox_id: str = ""
    summary: str = ""
    summary_trigger_tokens: int = 90000
    summary_trigger_messages: int = 0
    summary_keep_messages: int = 20
    summary_trim_tokens_to_summarize: int | None = 4000
    summary_offload_threshold_tokens: int = 1000
    summary_offload_preview_lines: int = 10
    summary_max_retention_ratio: float = 0.6
    summary_prompt: Annotated[str, {"__template_metadata__": {"kind": "prompt"}}] = ""
