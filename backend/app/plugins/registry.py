from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import PluginResourceRepository


async def resolve_resources_by_name(
    db: AsyncSession,
    *,
    kind: str,
    names: list[str],
    user_key: str | None = None,
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
        owner_user_key = str((item.config or {}).get("owner_user_key") or "") if item else ""
        if item and item.enabled and (not owner_user_key or owner_user_key == user_key):
            resolved.append(item.to_dict())
    return resolved


async def list_enabled_resources(db: AsyncSession, *, kind: str) -> list[dict]:
    """按资源类型读取所有启用资源，供运行时动态能力使用。"""
    repo = PluginResourceRepository(db)
    return [item.to_dict() for item in await repo.list(kind=kind, enabled_only=True)]


async def seed_builtin_resources(db: AsyncSession) -> None:
    """写入内置资源种子数据，包括示例 MCP、Skill、Subagent 和 Tool。"""
    repo = PluginResourceRepository(db)
    # 知识库工具由独立 middleware 注入，不作为通用运行时工具资源。
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
    ]
    for item in samples:
        await repo.upsert({"enabled": True, **item})

    # 导入工具包触发 @tool 注册，再从代码注册表自动同步内置工具资源。
    import app.agents.toolkits  # noqa: F401
    from app.agents.toolkits.registry import get_all_extra_metadata, get_all_tool_instances

    tool_configs = {
        "tavily_search": {
            "max_results": 5,
            "search_depth": "basic",
        },
    }
    extra_metadata = get_all_extra_metadata()
    for tool_instance in get_all_tool_instances():
        metadata = extra_metadata.get(tool_instance.name)
        if metadata is None or metadata.category != "buildin":
            continue

        display_name = metadata.display_name or tool_instance.name
        description = tool_instance.description or ""
        metadata_config = {
            "category": metadata.category,
            "tags": metadata.tags,
            "icon": metadata.icon,
            "config_guide": metadata.config_guide,
            "_builtin_defaults_version": 1,
        }
        default_config = {
            **tool_configs.get(tool_instance.name, {}),
            **metadata_config,
        }
        existing = await repo.get_by_name("tool", tool_instance.name)
        if existing is None:
            await repo.upsert(
                {
                    "kind": "tool",
                    "name": tool_instance.name,
                    "display_name": display_name,
                    "description": description,
                    "enabled": True,
                    "config": default_config,
                }
            )
            continue

        existing_config = existing.config or {}
        # 每个默认策略版本只迁移一次，之后保留管理员手动设置的开关状态。
        if int(existing_config.get("_builtin_defaults_version") or 0) < 1:
            existing.enabled = True

        # 同步代码定义的展示元数据，但保留工具业务配置。
        existing.display_name = display_name
        existing.description = description
        existing.config = {
            **existing_config,
            **metadata_config,
        }
        await db.commit()
