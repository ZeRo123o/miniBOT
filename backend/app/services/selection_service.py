from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import UserSelectionRepository


class SelectionService:
    def __init__(self, db: AsyncSession):
        """初始化用户资源选择仓储。"""
        self.selection_repo = UserSelectionRepository(db)

    async def get_or_default(self, user_key: str) -> dict:
        """读取用户资源选择；未配置时返回空选择。"""
        selection_item = await self.selection_repo.get(user_key)
        if selection_item:
            return selection_item.to_dict()
        return {"user_key": user_key, "mcps": [], "skills": [], "subagents": []}
