import logging

from langchain_core.tools import BaseTool

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.toolkits.registry import get_tool_instance

logger = logging.getLogger(__name__)


def resolve_runtime_tools(context: AgentContext) -> list[BaseTool]:
    """将当前上下文中已授权的工具资源解析为模型可调用的具体工具。"""
    resolved: list[BaseTool] = []
    seen: set[str] = set()

    for resource in context.tools:
        name = str(resource.get("name") or "").strip()
        if not name or name in seen:
            continue

        tool_instance = get_tool_instance(name)
        if tool_instance is None:
            logger.warning("运行时工具未找到可信执行器，已跳过: %s", name)
            continue

        resolved.append(tool_instance)
        seen.add(name)

    return resolved
