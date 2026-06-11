from typing import Any

from langchain.agents import create_agent
from langchain.agents.middleware import ToolCallLimitMiddleware

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.buildin.chatbot.prompt import build_system_prompt
from app.agents.buildin.chatbot.state import ChatBotState
from app.agents.toolkits import resolve_runtime_tools
from app.agents.middlewares import (
    KnowledgeBaseMiddleware,
    RuntimeConfigMiddleware,
    RuntimePromptMiddleware,
    SkillPromptMiddleware,
    SummaryMiddleware,
)
from app.llm import get_model


def build_chat_agent(context: AgentContext | None = None) -> Any:
    """根据运行时上下文创建 chat agent，并通过 middleware 提供具体工具。"""
    agent_context = context or AgentContext()
    runtime_tools = resolve_runtime_tools(agent_context)
    return create_agent(
        model=get_model(agent_context.model_use),
        tools=[],
        system_prompt=build_system_prompt(agent_context),
        middleware=[
            RuntimeConfigMiddleware(runtime_tools),
            KnowledgeBaseMiddleware(),
            ToolCallLimitMiddleware(
                run_limit=agent_context.max_tool_calls,
                exit_behavior="continue",
            ),
            SkillPromptMiddleware(),
            SummaryMiddleware(),
            RuntimePromptMiddleware(),
        ],
        state_schema=ChatBotState,
        context_schema=AgentContext,
        name="minibot-chat",
    )


def build_chat_graph(context: AgentContext | None = None) -> Any:
    """保留旧入口名称，内部转发到新的 create_agent 构建函数。"""
    return build_chat_agent(context)
