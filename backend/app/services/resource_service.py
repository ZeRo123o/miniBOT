from sqlalchemy.ext.asyncio import AsyncSession

from app.plugins.registry import list_enabled_resources
from app.repositories.skill_repository import SkillRepository


class ResourceService:
    def __init__(self, db: AsyncSession):
        """保存数据库会话，供资源解析函数使用。"""
        self.db = db

    async def resolve_enabled_resources(self, user_id: str) -> dict[str, list[dict]]:
        """Resolve globally enabled Tool/MCP resources visible to one user.

        Tool and MCP availability is controlled by each resource's global enabled
        flag. ``user_selections`` is intentionally not consulted here: it only
        stores the user's knowledge-base scope. A resource may still be private
        to its owner through ``config.owner_user_id``.
        """
        return {
            "mcps": await list_enabled_resources(self.db, kind="mcp", user_id=user_id),
            "skills": [
                item.to_dict()
                for item in await SkillRepository(self.db).list_all()
            ],
            "tools": await list_enabled_resources(self.db, kind="tool", user_id=user_id),
        }
