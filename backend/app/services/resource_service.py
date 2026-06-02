from sqlalchemy.ext.asyncio import AsyncSession

from app.plugins.registry import list_enabled_resources, resolve_resources_by_name


class ResourceService:
    def __init__(self, db: AsyncSession):
        """保存数据库会话，供资源解析函数使用。"""
        self.db = db

    async def resolve_for_selection(self, selection: dict) -> dict[str, list[dict]]:
        """解析 MCP、Skill、Subagent，并读取所有启用的运行时工具。"""
        return {
            "mcps": await resolve_resources_by_name(self.db, kind="mcp", names=selection["mcps"]),
            "skills": await resolve_resources_by_name(self.db, kind="skill", names=selection["skills"]),
            "subagents": await resolve_resources_by_name(self.db, kind="subagent", names=selection["subagents"]),
            "tools": await list_enabled_resources(self.db, kind="tool"),
        }
