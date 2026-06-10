from __future__ import annotations

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Conversation,
    ConversationMessage,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeDocument,
    PluginResource,
    UserSelection,
)


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

    async def delete_by_name(self, kind: str, name: str) -> None:
        """删除指定运行时资源，供种子数据清理废弃能力。"""
        await self.db.execute(
            delete(PluginResource).where(PluginResource.kind == kind, PluginResource.name == name)
        )
        await self.db.commit()

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

    async def save(
        self,
        user_key: str,
        mcps: list[str],
        skills: list[str],
        subagents: list[str],
        knowledge_base_ids: list[int],
    ) -> UserSelection:
        """保存用户启用的运行时资源和知识库范围。"""
        item = await self.get(user_key)
        if item is None:
            item = UserSelection(
                user_key=user_key,
                mcps=mcps,
                skills=skills,
                subagents=subagents,
                knowledge_base_ids=knowledge_base_ids,
            )
            self.db.add(item)
        else:
            item.mcps = mcps
            item.skills = skills
            item.subagents = subagents
            item.knowledge_base_ids = knowledge_base_ids
        await self.db.commit()
        await self.db.refresh(item)
        return item


class KnowledgeBaseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, user_key: str) -> list[KnowledgeBase]:
        result = await self.db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.user_key == user_key)
            .order_by(KnowledgeBase.updated_at.desc(), KnowledgeBase.id.desc())
        )
        return list(result.scalars().all())

    async def get(self, knowledge_base_id: int, user_key: str | None = None) -> KnowledgeBase | None:
        stmt = select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
        if user_key is not None:
            stmt = stmt.where(KnowledgeBase.user_key == user_key)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        description: str = "",
        user_key: str = "default",
        metadata: dict | None = None,
    ) -> KnowledgeBase:
        item = KnowledgeBase(
            name=name,
            description=description,
            user_key=user_key,
            metadata_=metadata or {},
        )
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def delete_with_selection_cleanup(self, knowledge_base: KnowledgeBase) -> None:
        """Delete a knowledge base and remove its ID from every saved workspace selection."""
        result = await self.db.execute(select(UserSelection))
        for selection in result.scalars().all():
            selected_ids = [int(item) for item in (selection.knowledge_base_ids or [])]
            if knowledge_base.id in selected_ids:
                selection.knowledge_base_ids = [
                    item for item in selected_ids if item != knowledge_base.id
                ]
        await self.db.delete(knowledge_base)
        await self.db.commit()


class KnowledgeDocumentRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, knowledge_base_id: int) -> list[KnowledgeDocument]:
        result = await self.db.execute(
            select(KnowledgeDocument)
            .where(KnowledgeDocument.knowledge_base_id == knowledge_base_id)
            .order_by(KnowledgeDocument.updated_at.desc(), KnowledgeDocument.id.desc())
        )
        return list(result.scalars().all())

    async def get(self, document_id: int) -> KnowledgeDocument | None:
        result = await self.db.execute(select(KnowledgeDocument).where(KnowledgeDocument.id == document_id))
        return result.scalar_one_or_none()

    async def get_by_ids(self, document_ids: list[int]) -> list[KnowledgeDocument]:
        if not document_ids:
            return []
        result = await self.db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id.in_(document_ids))
        )
        return list(result.scalars().all())

    async def get_by_hash(self, knowledge_base_id: int, file_hash: str) -> KnowledgeDocument | None:
        result = await self.db.execute(
            select(KnowledgeDocument).where(
                KnowledgeDocument.knowledge_base_id == knowledge_base_id,
                KnowledgeDocument.file_hash == file_hash,
            )
        )
        return result.scalar_one_or_none()

    async def create(self, data: dict) -> KnowledgeDocument:
        item = KnowledgeDocument(**data)
        self.db.add(item)
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            raise
        await self.db.refresh(item)
        return item

    async def update_status(
        self,
        document: KnowledgeDocument,
        *,
        status: str,
        markdown_object_key: str | None = None,
        error_message: str = "",
        metadata: dict | None = None,
    ) -> KnowledgeDocument:
        document.status = status
        document.error_message = error_message
        if markdown_object_key is not None:
            document.markdown_object_key = markdown_object_key
        if metadata is not None:
            document.metadata_ = metadata
        await self.db.commit()
        await self.db.refresh(document)
        return document

    async def delete(self, document: KnowledgeDocument) -> None:
        await self.db.delete(document)
        await self.db.commit()


class KnowledgeChunkRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_by_document(self, document_id: int) -> list[KnowledgeChunk]:
        result = await self.db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.document_id == document_id)
            .order_by(KnowledgeChunk.chunk_index, KnowledgeChunk.id)
        )
        return list(result.scalars().all())

    async def delete_by_document(self, document_id: int) -> None:
        await self.db.execute(delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id))
        await self.db.commit()

    async def bulk_create(self, rows: list[dict]) -> list[KnowledgeChunk]:
        if not rows:
            return []

        items = [KnowledgeChunk(**row) for row in rows]
        self.db.add_all(items)
        await self.db.commit()
        for item in items:
            await self.db.refresh(item)
        return items


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
