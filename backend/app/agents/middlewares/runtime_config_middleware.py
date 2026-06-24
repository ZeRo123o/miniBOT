from collections.abc import Callable
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import SystemMessage


class RuntimeConfigMiddleware(AgentMiddleware):
    """Refresh the runtime system prompt before every model call.

    Configured Tool and MCP resources are injected when the graph is built.
    Middleware-owned tools are collected by LangChain, and SkillsMiddleware adds
    dependencies only after the corresponding Skill has been activated.
    """

    def __init__(
        self,
        *,
        system_prompt_context_name: str = "system_prompt",
        enable_system_prompt_override: bool = True,
    ) -> None:
        super().__init__()
        self.system_prompt_context_name = system_prompt_context_name
        self.enable_system_prompt_override = enable_system_prompt_override

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        if not self.enable_system_prompt_override:
            return await handler(request)

        runtime_context = request.runtime.context
        system_prompt = getattr(runtime_context, self.system_prompt_context_name, "") or ""
        current_datetime = getattr(runtime_context, "current_datetime", "") or ""
        merged_system_prompt = (
            f"Current time: {current_datetime}\n\n{system_prompt}"
            if current_datetime
            else system_prompt
        )
        content_blocks = list(request.system_message.content_blocks) if request.system_message else []
        request = request.override(
            system_message=SystemMessage(
                content=[*content_blocks, {"type": "text", "text": merged_system_prompt}]
            )
        )
        return await handler(request)
