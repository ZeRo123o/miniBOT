from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware, TodoListMiddleware, ToolCallLimitMiddleware

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.buildin.chatbot.prompt import TODO_LIST_SYSTEM_PROMPT, build_system_prompt
from app.agents.buildin.chatbot.state import ChatBotState
from app.agents.checkpoints import checkpoint_manager
from app.agents.toolkits import resolve_runtime_tools
from app.agents.middlewares import (
    AttachmentMiddleware,
    KnowledgeBaseMiddleware,
    RuntimeConfigMiddleware,
    RuntimePromptMiddleware,
    SandboxMiddleware,
    SkillsMiddleware,
    SummaryMiddleware,
)
from app.agents.middlewares.subagent_middleware import SubAgentMiddleware
from app.llm import get_model


async def build_chat_agent(context: AgentContext | None = None) -> Any:
    """根据运行时上下文创建 chat agent，并通过 middleware 提供具体工具。"""
    agent_context = context or AgentContext()
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
    middleware = [
        RuntimeConfigMiddleware(runtime_tools),
        SandboxMiddleware(),
        AttachmentMiddleware(),
        KnowledgeBaseMiddleware(),
    ]
    if agent_context.allow_subagents:
        middleware.append(SubAgentMiddleware())
    middleware.extend(
        [
            ToolCallLimitMiddleware(
                run_limit=agent_context.max_tool_calls,
                exit_behavior="continue",
            ),
            SkillsMiddleware(skills_context_name="skills"),
            SummaryMiddleware(),
            RuntimePromptMiddleware(),
            TodoListMiddleware(system_prompt=TODO_LIST_SYSTEM_PROMPT),
            ModelRetryMiddleware(),
        ]
    )
    return create_agent(
        model=get_model(agent_context.model_use),
        tools=[],
        system_prompt=build_system_prompt(agent_context),
        middleware=middleware,
        state_schema=ChatBotState,
        context_schema=AgentContext,
        checkpointer=await checkpoint_manager.get(),
        name="minibot-chat",
    )


async def build_chat_graph(context: AgentContext | None = None) -> Any:
    """保留旧入口名称，内部转发到新的 create_agent 构建函数。"""
    return await build_chat_agent(context)
