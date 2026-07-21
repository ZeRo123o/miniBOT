from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ModelRetryMiddleware, TodoListMiddleware, ToolCallLimitMiddleware

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.buildin.chatbot.prompt import TODO_LIST_SYSTEM_PROMPT, build_system_prompt
from app.agents.buildin.chatbot.state import ChatBotState
from app.agents.checkpoints import checkpoint_manager
from app.agents.toolkits import merge_runtime_tools, resolve_runtime_mcps, resolve_runtime_tools
from app.agents.middlewares import (
    AttachmentMiddleware,
    CapabilityMiddleware,
    KnowledgeBaseMiddleware,
    RuntimeConfigMiddleware,
    RuntimePromptMiddleware,
    SandboxMiddleware,
    SkillsMiddleware,
    SummaryMiddleware,
    ToolOutputBudgetMiddleware,
)
from app.agents.middlewares.subagent_middleware import SubAgentMiddleware
from app.llm import get_model, get_model_by_spec


async def build_chat_agent(context: AgentContext | None = None) -> Any:
    """根据运行时上下文创建 chat agent，并通过 middleware 提供具体工具。"""
    agent_context = context or AgentContext()
    # two-layer tool assembly: configured resources are injected
    # at graph creation, while middleware contributes its own dynamic tools.
    runtime_tools = merge_runtime_tools(
        resolve_runtime_tools(agent_context, agent_type="chatbot"),
        await resolve_runtime_mcps(agent_context),
    )
    middleware = [
        RuntimeConfigMiddleware(),
        SandboxMiddleware(),
        AttachmentMiddleware(),
        KnowledgeBaseMiddleware(),
    ]
    if agent_context.allow_subagents:
        middleware.append(SubAgentMiddleware())
    middleware.extend(
        [
            ToolOutputBudgetMiddleware(),
            ToolCallLimitMiddleware(
                run_limit=agent_context.max_tool_calls,
                exit_behavior="continue",
            ),
            SkillsMiddleware(skills_context_name="skills"),
            CapabilityMiddleware(agent_type="chatbot"),
            SummaryMiddleware(),
            RuntimePromptMiddleware(),
            TodoListMiddleware(system_prompt=TODO_LIST_SYSTEM_PROMPT),
            ModelRetryMiddleware(),
        ]
    )
    model = get_model_by_spec(agent_context.model_spec) if agent_context.model_spec else get_model(agent_context.model_use)
    return create_agent(
        model=model,
        tools=runtime_tools,
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
