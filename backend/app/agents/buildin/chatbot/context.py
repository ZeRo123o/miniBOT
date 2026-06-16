from dataclasses import dataclass, field

from app.agents.buildin.chatbot.prompt import DEFAULT_SYSTEM_PROMPT
@dataclass(kw_only=True)
class AgentContext:
    user_key: str = "default"
    conversation_id: int | None = None
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    model_use: str = "chat_model"
    current_datetime: str = ""
    timezone: str = "Asia/Shanghai"
    mcps: list[dict] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    knowledge_base_ids: list[int] = field(default_factory=list)
    tool_events: list[dict] = field(default_factory=list)
    sandbox_id: str = ""
    max_tool_calls: int = 3
    summary: str = ""
    summary_trigger_tokens: int = 90000
    summary_trigger_messages: int = 0
    summary_keep_messages: int = 20
    summary_trim_tokens_to_summarize: int | None = 4000
    summary_offload_threshold_tokens: int = 1000
    summary_offload_preview_lines: int = 10
    summary_max_retention_ratio: float = 0.6
    summary_prompt: str = ""
