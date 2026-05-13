from dataclasses import dataclass, field

from app.graph.prompt import DEFAULT_SYSTEM_PROMPT


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
    active_tool_names: list[str] = field(default_factory=list)
    tool_events: list[dict] = field(default_factory=list)
    max_tool_calls: int = 3
    skill_prompt: str = ""
