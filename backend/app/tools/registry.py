from typing import Any

from app.agents.buildin.chatbot.context import AgentContext
from app.tools.governance import fail_tool_call, finish_tool_call, start_tool_call
from app.tools.tavily import tavily_search


def list_runtime_tool_specs(context: AgentContext) -> list[dict[str, Any]]:
    """返回当前上下文允许按需加载的工具元信息。"""
    return [
        {
            "name": item.get("name"),
            "display_name": item.get("display_name") or item.get("name"),
            "description": item.get("description", ""),
            "config": item.get("config") or {},
        }
        for item in context.tools
        if item.get("name")
    ]


def get_runtime_tool_spec(context: AgentContext, tool_name: str) -> dict[str, Any] | None:
    """根据工具名称从当前上下文中查找可用工具配置。"""
    for item in list_runtime_tool_specs(context):
        if item["name"] == tool_name:
            return item
    return None


async def run_runtime_tool(context: AgentContext, tool_name: str, query: str) -> str:
    """校验并执行一个运行时工具，同时记录工具调用事件。"""
    spec = get_runtime_tool_spec(context, tool_name)
    if spec is None:
        return f"工具 {tool_name} 不存在或当前用户未启用。"

    event, limit_error = start_tool_call(
        context,
        tool_name=tool_name,
        payload={"query": query},
    )
    if limit_error:
        return limit_error

    try:
        if tool_name == "tavily_search":
            result = await tavily_search(query=query, config=spec.get("config") or {})
        else:
            result = f"工具 {tool_name} 已注册，但后端还没有实现执行器。"
    except Exception as error:
        fail_tool_call(event, error)
        return f"工具 {tool_name} 调用失败：{error}"

    finish_tool_call(event)
    return result
