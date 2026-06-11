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
    skills: list[dict] = field(default_factory=list)
    subagents: list[dict] = field(default_factory=list)
    tools: list[dict] = field(default_factory=list)
    knowledge_base_ids: list[int] = field(default_factory=list)
    tool_events: list[dict] = field(default_factory=list)
    max_tool_calls: int = 3
    summary: str = ""
    summary_context_window_tokens: int = 128000
    summary_trigger_ratio: float = 0.7
    summary_trigger_tokens: int = 90000
    summary_keep_messages: int = 8
    summary_max_chars: int = 3000
