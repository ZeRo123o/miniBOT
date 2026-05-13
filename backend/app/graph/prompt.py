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
    """根据运行时上下文生成 MCP、Skill、Subagent 和 Tool 的资源摘要。"""
    mcps = _resource_names(_get_value(context, "mcps", []))
    skills = _resource_names(_get_value(context, "skills", []))
    subagents = _resource_names(_get_value(context, "subagents", []))
    tools = _resource_names(_get_value(context, "tools", []))
    return (
        "当前启用资源:\n"
        f"- MCP: {mcps or '无'}\n"
        f"- Skill: {skills or '无'}\n"
        f"- Subagent: {subagents or '无'}\n"
        f"- Tool: {tools or '无'}"
    )


def build_system_prompt(context: Any, base_prompt: str | None = None) -> str:
    """组装最终 system prompt，包含基础提示词、资源上下文和工具策略。"""
    prompt = base_prompt or _get_value(context, "system_prompt", DEFAULT_SYSTEM_PROMPT)
    parts = [
        prompt,
        build_time_context(context),
        build_resource_context(context),
    ]
    skill_prompt = _get_value(context, "skill_prompt", "")
    if skill_prompt:
        parts.append(skill_prompt)
    if _get_value(context, "tools", []):
        parts.append(
            "工具调用策略:\n"
            "- 不要假装已经访问网页或外部系统。\n"
            "- 当问题涉及最新信息、网页资料、新闻、价格、版本变化或不确定事实时，使用 dynamic_tool_call 按名称调用运行时工具。\n"
            "- 可先调用 list_available_tools 查看当前允许的工具。\n"
            "- 工具结果只作为上下文，最终回答仍需要你归纳整理。"
        )
    return "\n\n".join(parts)


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
