from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import PluginResourceRepository


async def resolve_resources_by_name(
    db: AsyncSession,
    *,
    kind: str,
    names: list[str],
) -> list[dict]:
    """按名称解析用户选择的资源，并过滤未启用或重复的资源。"""
    repo = PluginResourceRepository(db)
    resolved = []
    seen = set()
    for name in names:
        if name in seen:
            continue
        seen.add(name)
        item = await repo.get_by_name(kind, name)
        if item and item.enabled:
            resolved.append(item.to_dict())
    return resolved


async def list_enabled_resources(db: AsyncSession, *, kind: str) -> list[dict]:
    """按资源类型读取所有启用资源，供运行时动态能力使用。"""
    repo = PluginResourceRepository(db)
    return [item.to_dict() for item in await repo.list(kind=kind, enabled_only=True)]


async def seed_builtin_resources(db: AsyncSession) -> None:
    """写入内置资源种子数据，包括示例 MCP、Skill、Subagent 和 Tool。"""
    repo = PluginResourceRepository(db)
    # 知识库工具改由 middleware 直接注入，不再注册为 dynamic_tool_call 资源。
    await repo.delete_by_name("tool", "knowledge_query")
    samples = [
        {
            "kind": "mcp",
            "name": "filesystem",
            "display_name": "Filesystem MCP",
            "description": "Example MCP server placeholder.",
            "config": {"transport": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]},
        },
        {
            "kind": "skill",
            "name": "reporter",
            "display_name": "Reporter Skill",
            "description": "Draft structured reports from gathered context.",
            "config": {"prompt_path": "skills/reporter/SKILL.md", "dependencies": {"mcps": [], "skills": []}},
        },
        {
            "kind": "subagent",
            "name": "researcher",
            "display_name": "Researcher Subagent",
            "description": "A focused helper for research and source synthesis.",
            "config": {"system_prompt": "You are a concise research subagent.", "tools": []},
        },
        {
            "kind": "tool",
            "name": "tavily_search",
            "display_name": "Tavily 网页搜索",
            "description": "按需搜索网页，适合最新信息、新闻、资料查证和外部事实查询。",
            "config": {"max_results": 5, "search_depth": "basic"},
        },
    ]
    for item in samples:
        await repo.upsert({"enabled": True, **item})
