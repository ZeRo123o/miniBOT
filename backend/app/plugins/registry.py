from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp import BUILTIN_MCP_SERVERS
from app.agents.skills.buildin import sync_builtin_skills
from app.db.repositories import PluginResourceRepository

TOOL_DEFAULTS_VERSION = 2


async def list_enabled_resources(
    db: AsyncSession,
    *,
    kind: str,
    user_id: str | None = None,
) -> list[dict]:
    """读取全局或当前用户拥有的已启用资源。"""
    repo = PluginResourceRepository(db)
    resources = []
    for item in await repo.list(kind=kind, enabled_only=True):
        owner_user_id = str((item.config or {}).get("owner_user_id") or "")
        if not owner_user_id or owner_user_id == user_id:
            resources.append(item.to_dict())
    return resources


async def seed_builtin_resources(db: AsyncSession) -> None:
    """同步内置 MCP、Tool 以及独立表中的 Skill 元数据。"""
    repo = PluginResourceRepository(db)
    # 知识库工具由独立 middleware 注入，不作为通用运行时工具资源。
    await repo.delete_by_name("tool", "knowledge_query")
    await repo.delete_by_name("tool", "task")
    for sandbox_tool_name in (
        "sandbox_read_file",
        "sandbox_write_file",
        "sandbox_ls",
        "sandbox_glob",
        "sandbox_grep",
    ):
        await repo.delete_by_name("tool", sandbox_tool_name)
    await repo.delete_by_kind("subagent")
    samples = [
        {
            "kind": "mcp",
            "name": "filesystem",
            "display_name": "Filesystem MCP",
            "description": "Example MCP server placeholder.",
            "config": {"transport": "stdio", "command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem"]},
        },
    ]
    for item in [*BUILTIN_MCP_SERVERS, *samples]:
        await repo.upsert({"enabled": False, **item})

    # Skill 不再写入 plugin_resources，而是同步到独立 skills 表和运行时目录。
    await sync_builtin_skills(db)

    # 导入工具包触发 @tool 注册，再从代码注册表自动同步内置工具资源。
    import app.agents.toolkits  # noqa: F401
    from app.agents.toolkits.registry import get_all_extra_metadata, get_all_tool_instances

    tool_configs = {
        "tavily_search": {
            "exposure": "skill_only",
            "max_results": 5,
            "search_depth": "basic",
        },
    }
    extra_metadata = get_all_extra_metadata()
    for tool_instance in get_all_tool_instances():
        metadata = extra_metadata.get(tool_instance.name)
        if metadata is None or metadata.category not in {"buildin", "external"}:
            continue

        is_builtin = metadata.category == "buildin"
        display_name = metadata.display_name or tool_instance.name
        description = tool_instance.description or ""
        metadata_config = {
            "origin": "builtin" if is_builtin else "plugin",
            "category": metadata.category,
            "tags": metadata.tags,
            "icon": metadata.icon,
            "config_guide": metadata.config_guide,
            "_tool_defaults_version": TOOL_DEFAULTS_VERSION,
        }
        default_config = {
            "exposure": "direct",
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
                    "enabled": is_builtin,
                    "config": default_config,
                }
            )
            continue

        existing_config = existing.config or {}
        # 清理旧版按模型调用动态注入工具时使用的开关。
        existing_config.pop("allow_skill_dependency", None)
        existing_config.pop("expose_directly", None)
        existing_config["origin"] = "builtin" if is_builtin else "plugin"
        previous_defaults_version = int(
            existing_config.get("_tool_defaults_version") or 0
        )
        # 缺失值始终补齐，已有显式 exposure 始终保留管理员选择。
        existing_config.setdefault(
            "exposure",
            tool_configs.get(tool_instance.name, {}).get(
                "exposure",
                "direct",
            ),
        )
        # 每个默认策略版本只迁移一次，之后保留管理员手动设置的开关状态。
        if is_builtin and previous_defaults_version < 1:
            existing.enabled = True

        # 同步代码定义的展示元数据，但保留工具业务配置。
        existing.display_name = display_name
        existing.description = description
        existing.config = {
            **existing_config,
            **metadata_config,
        }
        await db.commit()
