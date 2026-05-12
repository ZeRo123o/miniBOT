from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Conversation, ConversationMessage, PluginResource, UserSelection


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


class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, user_key: str, include_archived: bool = False) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_key == user_key)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        )
        if not include_archived:
            stmt = stmt.where(Conversation.archived.is_(False))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, conversation_id: int, user_key: str | None = None) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        if user_key is not None:
            stmt = stmt.where(Conversation.user_key == user_key)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, user_key: str, title: str = "新对话") -> Conversation:
        item = Conversation(user_key=user_key, title=title)
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def update(
        self,
        conversation: Conversation,
        title: str | None = None,
        archived: bool | None = None,
    ) -> Conversation:
        if title is not None:
            conversation.title = title
        if archived is not None:
            conversation.archived = archived
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def touch(self, conversation: Conversation) -> Conversation:
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation.id)
            .values(updated_at=func.now())
        )
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation


class ConversationMessageRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, conversation_id: int) -> list[ConversationMessage]:
        result = await self.db.execute(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == conversation_id)
            .order_by(ConversationMessage.created_at, ConversationMessage.id)
        )
        return list(result.scalars().all())

    async def create(
        self,
        conversation_id: int,
        role: str,
        content: str,
        metadata: dict | None = None,
    ) -> ConversationMessage:
        item = ConversationMessage(
            conversation_id=conversation_id,
            role=role,
            content=content,
            metadata_=metadata or {},
        )
        self.db.add(item)
        await self.db.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=func.now())
        )
        await self.db.commit()
        await self.db.refresh(item)
        return item
