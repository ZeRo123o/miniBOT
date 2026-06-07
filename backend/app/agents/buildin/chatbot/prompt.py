from typing import Any

DEFAULT_SYSTEM_PROMPT = "You are miniBOT, a modular assistant."


def _get_value(source: Any, name: str, default: Any) -> Any:
    """兼容 dict 和 dataclass 两种上下文读取方式。"""
    if isinstance(source, dict):
        return source.get(name, default)
    return getattr(source, name, default)


def _resource_names(items: list[dict]) -> list[str]:
    """从资源字典列表中提取用于展示给模型的资源名称。"""
    return [item.get("display_name") or item.get("name", "") for item in items if item.get("name")]


def build_resource_context(context: Any) -> str:
    """生成由通用运行时中间件负责注入的资源摘要。"""
    mcps = _resource_names(_get_value(context, "mcps", []))
    subagents = _resource_names(_get_value(context, "subagents", []))
    tools = _resource_names(_get_value(context, "tools", []))
    return (
        "当前启用资源:\n"
        f"- MCP: {mcps or '无'}\n"
        f"- Subagent: {subagents or '无'}\n"
        f"- Tool: {tools or '无'}"
    )


def build_system_prompt(context: Any, base_prompt: str | None = None) -> str:
    """创建 Agent 时组装稳定的基础 system prompt。"""
    prompt = base_prompt or _get_value(context, "system_prompt", DEFAULT_SYSTEM_PROMPT)
    return "\n\n".join([prompt, build_time_context(context)])


def build_runtime_prompt(context: Any) -> str:
    """生成每次模型调用前追加的资源与工具策略。"""
    parts = [build_resource_context(context)]
    if _get_value(context, "tools", []):
        parts.append(
            "工具调用策略:\n"
            "- 不要假装已经访问网页或外部系统。\n"
            "- 当问题涉及最新信息、网页资料、新闻、价格、版本变化或不确定事实时，使用 dynamic_tool_call 按名称调用运行时工具。\n"
            "- 可先调用 list_available_tools 查看当前允许的工具。\n"
            "- 工具结果只作为上下文，最终回答仍需要你归纳整理。"
        )
    if _get_value(context, "knowledge_base_ids", []):
        parts.append(
            "知识库工具调用策略:\n"
            "- 使用 list_kbs 查看当前会话已启用的知识库及其 kb_id。\n"
            "- 当问题需要依据知识库文档回答时，使用 query_kb 查询指定知识库。\n"
            "- 回答时保留 query_kb 结果中的 citation_id，不要编造知识库内容或引用。"
        )
    return "\n\n".join(parts)


def build_skill_prompt(context: Any) -> str:
    """生成 Skill 元数据提示段，具体能力仍由对应运行时资源提供。"""
    skills = _get_value(context, "skills", [])
    lines = []
    for item in skills:
        name = item.get("display_name") or item.get("name", "")
        runtime_name = item.get("name", "")
        if not runtime_name:
            continue
        description = str(item.get("description") or "").strip()
        label = f"{name} (`{runtime_name}`)" if name != runtime_name else f"`{runtime_name}`"
        lines.append(f"- {label}: {description}" if description else f"- {label}")
    if not lines:
        return ""
    return "当前启用 Skills:\n" + "\n".join(lines)


def build_time_context(context: Any) -> str:
    """根据运行时上下文生成当前时间说明，约束模型处理相对时间。"""
    current_datetime = _get_value(context, "current_datetime", "")
    timezone = _get_value(context, "timezone", "Asia/Shanghai")
    if not current_datetime:
        return f"当前时区: {timezone}"
    return (
        f"当前时间: {current_datetime}\n"
        f"当前时区: {timezone}\n"
        "当用户提到今天、明天、昨天、当前、最新、最近等相对时间时，必须以这里的当前时间为准。"
    )
