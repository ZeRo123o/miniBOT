from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PluginResource, UserSelection


class PluginResourceRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, kind: str | None = None, enabled_only: bool = False) -> list[PluginResource]:
        stmt = select(PluginResource).order_by(PluginResource.kind, PluginResource.name)
        if kind:
            stmt = stmt.where(PluginResource.kind == kind)
        if enabled_only:
            stmt = stmt.where(PluginResource.enabled.is_(True))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_by_name(self, kind: str, name: str) -> PluginResource | None:
        result = await self.db.execute(
            select(PluginResource).where(PluginResource.kind == kind, PluginResource.name == name)
        )
        return result.scalar_one_or_none()

    async def upsert(self, data: dict) -> PluginResource:
        item = await self.get_by_name(data["kind"], data["name"])
        if item is None:
            item = PluginResource(**data)
            self.db.add(item)
        else:
            for key, value in data.items():
                if key not in {"id", "kind", "name"}:
                    setattr(item, key, value)
        await self.db.commit()
        await self.db.refresh(item)
        return item


class UserSelectionRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get(self, user_key: str) -> UserSelection | None:
        result = await self.db.execute(select(UserSelection).where(UserSelection.user_key == user_key))
        return result.scalar_one_or_none()

    async def save(self, user_key: str, mcps: list[str], skills: list[str], subagents: list[str]) -> UserSelection:
        item = await self.get(user_key)
        if item is None:
            item = UserSelection(user_key=user_key, mcps=mcps, skills=skills, subagents=subagents)
            self.db.add(item)
        else:
            item.mcps = mcps
            item.skills = skills
            item.subagents = subagents
        await self.db.commit()
        await self.db.refresh(item)
        return item
