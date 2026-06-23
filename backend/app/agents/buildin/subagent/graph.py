from collections.abc import Callable
from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import (
    AgentMiddleware,
    ModelRequest,
    ModelResponse,
    ModelRetryMiddleware,
    ToolCallLimitMiddleware,
)

from app.agents.buildin.chatbot.prompt import build_system_prompt
from app.agents.buildin.subagent.state import SubAgentState
from app.agents.checkpoints import checkpoint_manager
from app.agents.middlewares.subagent_middleware import SubAgentContext
from app.agents.backends.sandbox.middleware import SandboxMiddleware
from app.agents.middlewares.attachment import AttachmentMiddleware
from app.agents.middlewares.knowledge_base import KnowledgeBaseMiddleware
from app.agents.middlewares.runtime_config_middleware import RuntimeConfigMiddleware
from app.agents.middlewares.runtime_prompt import RuntimePromptMiddleware
from app.agents.middlewares.Skills_middleware import SkillsMiddleware
from app.agents.middlewares.summary_middleware import SummaryMiddleware
from app.agents.toolkits import resolve_runtime_tools
from app.llm import get_model

_SUBAGENT_DISABLED_TOOLS = frozenset({"ask_user_question", "install_skill", "present_artifacts", "task"})


class _SubAgentToolFilterMiddleware(AgentMiddleware):
    """Remove parent-only tools from subagent model requests."""

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return handler(request.override(tools=self._filter_tools(request.tools or [])))

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        return await handler(request.override(tools=self._filter_tools(request.tools or [])))

    @staticmethod
    def _filter_tools(tools: list[Any]) -> list[Any]:
        return [
            tool
            for tool in tools
            if str(getattr(tool, "name", "") or "") not in _SUBAGENT_DISABLED_TOOLS
        ]


async def build_subagent_agent(context: SubAgentContext | None = None) -> Any:
    """Build an isolated subagent graph for task delegation."""
    agent_context = context or SubAgentContext()
    candidate_tool_names = [
        str(resource.get("name") or "")
        for resource in agent_context.tools
        if resource.get("name")
        and (resource.get("config") or {}).get("allow_skill_dependency", True) is not False
    ]
    runtime_tools = resolve_runtime_tools(
        agent_context,
        extra_tool_names=candidate_tool_names,
    )
    return create_agent(
        model=get_model(agent_context.model_use),
        tools=[],
        system_prompt=build_system_prompt(agent_context),
        middleware=[
            RuntimeConfigMiddleware(runtime_tools),
            SandboxMiddleware(),
            AttachmentMiddleware(),
            KnowledgeBaseMiddleware(),
            ToolCallLimitMiddleware(
                run_limit=agent_context.max_tool_calls,
                exit_behavior="continue",
            ),
            SkillsMiddleware(skills_context_name="skills"),
            SummaryMiddleware(),
            RuntimePromptMiddleware(),
            _SubAgentToolFilterMiddleware(),
            ModelRetryMiddleware(),
        ],
        state_schema=SubAgentState,
        context_schema=SubAgentContext,
        checkpointer=await checkpoint_manager.get(),
        name="minibot-subagent",
    )
