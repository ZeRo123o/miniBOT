from typing import Any

DEFAULT_SYSTEM_PROMPT = "You are miniBOT, a modular assistant."

TODO_LIST_SYSTEM_PROMPT = """
## 任务进度

仅当任务确实复杂时才使用 `write_todos`：例如需要三个及以上相互关联的步骤、多个工具调用、跨文件分析，或执行过程中需要根据结果调整计划的任务。

- 简单问答、单一步骤操作、简短解释和可直接完成的请求不要创建待办。
- 创建待办后，马上将正在执行的第一项标记为 `in_progress`。
- 每完成一项立即更新为 `completed`，不要等到任务结束后再批量更新。
- 待办标题应简短、具体、面向用户可见；不要包含敏感信息、完整文件内容或冗长内部推理。
- 发现新依赖、风险或工作项时可以调整未完成待办；所有工作完成后将相应项目标记为 `completed`。
""".strip()


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
    tools = _resource_names(_get_value(context, "tools", []))
    return (
        "当前启用资源:\n"
        f"- MCP: {mcps or '无'}\n"
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
            "- 当问题涉及最新信息、网页资料、新闻、价格、版本变化或不确定事实时，调用当前提供的具体工具。\n"
            "- 严格按照工具参数说明构造调用参数，不要调用未提供的工具。\n"
            "- 工具结果只作为上下文，最终回答仍需要你归纳整理。"
        )
    tool_names = {
        str(item.get("name") or "")
        for item in _get_value(context, "tools", [])
    }
    if any(name.startswith("sandbox_") for name in tool_names):
        parts.append(
            "沙盒文件策略:\n"
            "- 只使用 /mnt/user-data/workspace、/mnt/user-data/uploads、"
            "/mnt/user-data/outputs 和 /mnt/skills 虚拟路径。\n"
            "- uploads 和 skills 只读；中间文件写入 workspace，最终交付物写入 outputs。\n"
            "- 生成最终文件后，使用 present_artifacts 展示 outputs 中的文件。\n"
            "- 不要猜测或泄漏宿主机真实路径。"
        )
    if _get_value(context, "knowledge_base_ids", []):
        parts.append(
            "知识库工具调用策略:\n"
            "- 使用 list_kbs 查看当前会话已启用的知识库及其 kb_id。\n"
            "- 当问题需要依据知识库文档回答时，使用 query_kb 查询指定知识库。\n"
            "- 回答时保留 query_kb 结果中的 citation_id，不要编造知识库内容或引用。"
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
