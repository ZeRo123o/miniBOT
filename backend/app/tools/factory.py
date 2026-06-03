from langchain_core.tools import tool

from app.agents.buildin.chatbot.context import AgentContext
from app.tools.registry import list_runtime_tool_specs, run_runtime_tool


def get_runtime_tools(context: AgentContext) -> list:
    """创建只包含工具路由能力的 LangChain tools，具体工具在调用时动态执行。"""

    @tool("list_available_tools")
    async def list_available_tools() -> str:
        """列出当前用户允许按需调用的运行时工具。"""
        specs = list_runtime_tool_specs(context)
        if not specs:
            return "当前没有可用的运行时工具。"
        lines = ["当前可用运行时工具:"]
        for spec in specs:
            lines.append(f"- {spec['name']}: {spec.get('description') or spec.get('display_name')}")
        return "\n".join(lines)

    @tool("dynamic_tool_call")
    async def dynamic_tool_call(tool_name: str, query: str) -> str:
        """按工具名称在运行时加载并执行工具；query 是要交给该工具处理的问题。"""
        return await run_runtime_tool(context=context, tool_name=tool_name, query=query)

    return [list_available_tools, dynamic_tool_call]
