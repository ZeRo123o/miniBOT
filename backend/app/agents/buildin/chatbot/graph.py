from typing import Any

from langchain.agents import create_agent

from app.agents.buildin.chatbot.context import AgentContext
from app.graph.middleware import (
    RuntimePromptMiddleware,
    RuntimeResourceMiddleware,
    SkillPromptMiddleware,
    SummaryMiddleware,
)
from app.llm import get_model
from app.tools import get_runtime_tools


def build_chat_agent(context: AgentContext | None = None) -> Any:
    """根据运行时上下文创建 chat agent，并只绑定动态工具路由能力。"""
    agent_context = context or AgentContext()
    return create_agent(
        model=get_model(agent_context.model_use),
        tools=get_runtime_tools(agent_context),
        middleware=[
            RuntimeResourceMiddleware(),
            SkillPromptMiddleware(),
            SummaryMiddleware(),
            RuntimePromptMiddleware(),
        ],
        context_schema=AgentContext,
        name="minibot-chat",
    )


def build_chat_graph(context: AgentContext | None = None) -> Any:
    """保留旧入口名称，内部转发到新的 create_agent 构建函数。"""
    return build_chat_agent(context)
