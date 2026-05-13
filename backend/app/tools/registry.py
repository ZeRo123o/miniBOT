from typing import Any

from app.agent.context import AgentContext
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
    if len(context.tool_events) >= context.max_tool_calls:
        return f"工具调用次数已达到上限 {context.max_tool_calls}，本轮不再继续调用工具。"

    spec = get_runtime_tool_spec(context, tool_name)
    if spec is None:
        return f"工具 {tool_name} 不存在或当前用户未启用。"

    context.active_tool_names.append(tool_name)
    context.tool_events.append({"tool_name": tool_name, "query": query, "status": "started"})

    try:
        if tool_name == "tavily_search":
            result = await tavily_search(query=query, config=spec.get("config") or {})
        else:
            result = f"工具 {tool_name} 已注册，但后端还没有实现执行器。"
    except Exception as error:
        context.tool_events[-1]["status"] = "failed"
        context.tool_events[-1]["error"] = str(error)
        return f"工具 {tool_name} 调用失败：{error}"

    context.tool_events[-1]["status"] = "finished"
    return result
