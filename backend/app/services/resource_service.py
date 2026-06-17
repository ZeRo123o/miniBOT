from sqlalchemy.ext.asyncio import AsyncSession

from app.plugins.registry import list_enabled_resources
from app.repositories.skill_repository import SkillRepository


class ResourceService:
    def __init__(self, db: AsyncSession):
        """保存数据库会话，供资源解析函数使用。"""
        self.db = db

    async def resolve_for_selection(self, selection: dict) -> dict[str, list[dict]]:
        """读取扩展管理中启用的 MCP、Skill 和运行时工具。"""
        user_id = selection.get("user_id")
        return {
            "mcps": await list_enabled_resources(self.db, kind="mcp", user_id=user_id),
            "skills": [
                item.to_dict()
                for item in await SkillRepository(self.db).list_all()
            ],
            "tools": await list_enabled_resources(self.db, kind="tool", user_id=user_id),
        }
