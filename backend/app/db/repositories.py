from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Conversation,
    ConversationMessage,
    AgentRun,
    EvaluationDataset,
    EvaluationDatasetItem,
    EvaluationRun,
    EvaluationRunItem,
    KnowledgeBase,
    KnowledgeChunk,
    KnowledgeGraphEntity,
    KnowledgeGraphEntityMention,
    KnowledgeGraphTriple,
    KnowledgeGraphTripleMention,
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

    async def delete_by_kind(self, kind: str) -> None:
        """删除已经退出资源契约的整个资源类型。"""
        await self.db.execute(delete(PluginResource).where(PluginResource.kind == kind))
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

    async def get(self, user_id: str) -> UserSelection | None:
        result = await self.db.execute(select(UserSelection).where(UserSelection.user_id == user_id))
        return result.scalar_one_or_none()

    async def save(
        self,
        user_id: str,
        knowledge_base_ids: list[int],
    ) -> UserSelection:
        """只保存用户选择的知识库范围，旧资源列固定清空以兼容现有数据库。"""
        item = await self.get(user_id)
        if item is None:
            item = UserSelection(
                user_id=user_id,
                mcps=[],
                skills=[],
                subagents=[],
                knowledge_base_ids=knowledge_base_ids,
            )
            self.db.add(item)
        else:
            item.mcps = []
            item.skills = []
            item.subagents = []
            item.knowledge_base_ids = knowledge_base_ids
        await self.db.commit()
        await self.db.refresh(item)
        return item


class KnowledgeBaseRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, user_id: str) -> list[KnowledgeBase]:
        result = await self.db.execute(
            select(KnowledgeBase)
            .where(KnowledgeBase.user_id == user_id)
            .order_by(KnowledgeBase.updated_at.desc(), KnowledgeBase.id.desc())
        )
        return list(result.scalars().all())

    async def get(self, knowledge_base_id: int, user_id: str | None = None) -> KnowledgeBase | None:
        stmt = select(KnowledgeBase).where(KnowledgeBase.id == knowledge_base_id)
        if user_id is not None:
            stmt = stmt.where(KnowledgeBase.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        name: str,
        description: str = "",
        user_id: str = "default",
        metadata: dict | None = None,
    ) -> KnowledgeBase:
        runtime_metadata = dict(metadata or {})
        item = KnowledgeBase(
            name=name,
            description=description,
            user_id=user_id,
            created_by=user_id,
            embedding_model_spec=runtime_metadata.pop("embedding_model_spec", None),
            llm_model_spec=runtime_metadata.pop("extraction_model_spec", None),
            query_params=runtime_metadata.pop("query_params", {}) or {},
            additional_params=runtime_metadata,
            share_config={
                "access_level": "private",
                "department_ids": [],
                "user_uids": [user_id],
            },
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

    async def update_metadata(self, knowledge_base: KnowledgeBase, metadata: dict) -> KnowledgeBase:
        knowledge_base.apply_runtime_metadata(metadata)
        await self.db.commit()
        await self.db.refresh(knowledge_base)
        return knowledge_base


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

    async def list_by_knowledge_base(self, knowledge_base_id: int) -> list[KnowledgeChunk]:
        result = await self.db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.knowledge_base_id == knowledge_base_id)
            .order_by(KnowledgeChunk.document_id, KnowledgeChunk.chunk_index, KnowledgeChunk.id)
        )
        return list(result.scalars().all())

    async def count_by_knowledge_base(self, knowledge_base_id: int) -> int:
        """统计知识库内参与检索和图构建的单层 Chunk。"""
        result = await self.db.execute(
            select(func.count(KnowledgeChunk.id)).where(
                KnowledgeChunk.knowledge_base_id == knowledge_base_id,
            )
        )
        return int(result.scalar_one() or 0)

    async def count_graph_pending_by_knowledge_base(
        self,
        knowledge_base_id: int,
    ) -> int:
        result = await self.db.execute(
            select(func.count(KnowledgeChunk.id)).where(
                KnowledgeChunk.knowledge_base_id == knowledge_base_id,
                KnowledgeChunk.graph_indexed.is_(False),
            )
        )
        return int(result.scalar_one() or 0)

    async def count_graph_indexed_by_knowledge_base(
        self,
        knowledge_base_id: int,
    ) -> int:
        result = await self.db.execute(
            select(func.count(KnowledgeChunk.id)).where(
                KnowledgeChunk.knowledge_base_id == knowledge_base_id,
                KnowledgeChunk.graph_indexed.is_(True),
            )
        )
        return int(result.scalar_one() or 0)

    async def list_graph_pending_by_knowledge_base(
        self,
        knowledge_base_id: int,
        limit: int,
    ) -> list[dict[str, Any]]:
        """返回纯数据快照，避免并发任务持有会过期的 ORM 实例。"""
        result = await self.db.execute(
            select(
                KnowledgeChunk.chunk_id,
                KnowledgeChunk.knowledge_base_id,
                KnowledgeChunk.document_id,
                KnowledgeChunk.chunk_index,
                KnowledgeChunk.content,
                KnowledgeChunk.token_count,
                KnowledgeChunk.start_char_pos,
                KnowledgeChunk.end_char_pos,
                KnowledgeChunk.metadata_.label("metadata"),
                KnowledgeChunk.graph_indexed,
                KnowledgeChunk.ent_ids,
                KnowledgeChunk.extraction_result,
            )
            .where(
                KnowledgeChunk.knowledge_base_id == knowledge_base_id,
                KnowledgeChunk.graph_indexed.is_(False),
            )
            .order_by(KnowledgeChunk.document_id, KnowledgeChunk.chunk_index)
            .limit(max(int(limit), 1))
        )
        return [dict(row) for row in result.mappings().all()]

    async def update_extraction_result(
        self,
        chunk_id: str,
        extraction_result: dict,
    ) -> None:
        await self.db.execute(
            update(KnowledgeChunk)
            .where(KnowledgeChunk.chunk_id == chunk_id)
            .values(extraction_result=extraction_result)
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()

    async def mark_graph_indexed(
        self,
        chunk_id: str,
        *,
        ent_ids: list[str],
    ) -> None:
        await self.db.execute(
            update(KnowledgeChunk)
            .where(KnowledgeChunk.chunk_id == chunk_id)
            .values(graph_indexed=True, ent_ids=ent_ids)
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()

    async def reset_graph_state_by_knowledge_base(
        self,
        knowledge_base_id: int,
        clear_extraction_result: bool,
    ) -> int:
        values: dict[str, Any] = {
            "graph_indexed": False,
            "ent_ids": None,
        }
        if clear_extraction_result:
            values["extraction_result"] = None
        result = await self.db.execute(
            update(KnowledgeChunk)
            .where(
                KnowledgeChunk.knowledge_base_id == knowledge_base_id,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        await self.db.commit()
        return int(result.rowcount or 0)

    async def list_by_chunk_ids(self, chunk_ids: list[str]) -> list[KnowledgeChunk]:
        normalized_ids = [str(chunk_id) for chunk_id in chunk_ids if str(chunk_id).strip()]
        if not normalized_ids:
            return []
        result = await self.db.execute(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.chunk_id.in_(normalized_ids))
            .order_by(KnowledgeChunk.document_id, KnowledgeChunk.chunk_index, KnowledgeChunk.id)
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


class KnowledgeGraphRepository:
    """维护 PostgreSQL 中可重建的图实体、关系和证据映射。"""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def upsert_chunk_graph(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        chunk_id: str,
        entities: list[dict],
        triples: list[dict],
    ) -> None:
        """增量保存一个 Chunk 的实体、三元组及证据映射。"""
        await self.db.execute(
            delete(KnowledgeGraphTripleMention).where(
                KnowledgeGraphTripleMention.chunk_id == chunk_id
            )
        )
        await self.db.execute(
            delete(KnowledgeGraphEntityMention).where(
                KnowledgeGraphEntityMention.chunk_id == chunk_id
            )
        )
        for data in entities:
            result = await self.db.execute(
                select(KnowledgeGraphEntity).where(
                    KnowledgeGraphEntity.entity_id == data["entity_id"]
                )
            )
            entity = result.scalar_one_or_none()
            if entity is None:
                entity = KnowledgeGraphEntity(
                    knowledge_base_id=knowledge_base_id,
                    entity_id=data["entity_id"],
                    name=data["name"],
                    normalized_name=data["normalized_name"],
                    entity_type=data.get("label") or data.get("entity_type") or "Entity",
                    description=data.get("description") or data.get("content") or "",
                )
                self.db.add(entity)
            else:
                description = data.get("description") or data.get("content") or ""
                if len(description) > len(entity.description):
                    entity.description = description
        await self.db.flush()
        for data in entities:
            for evidence_chunk_id in data.get("chunk_ids") or [chunk_id]:
                self.db.add(
                    KnowledgeGraphEntityMention(
                        knowledge_base_id=knowledge_base_id,
                        document_id=document_id,
                        chunk_id=evidence_chunk_id,
                        entity_id=data["entity_id"],
                    )
                )

        for data in triples:
            result = await self.db.execute(
                select(KnowledgeGraphTriple).where(
                    KnowledgeGraphTriple.triple_id == data["triple_id"]
                )
            )
            triple = result.scalar_one_or_none()
            if triple is None:
                triple = KnowledgeGraphTriple(
                    knowledge_base_id=knowledge_base_id,
                    triple_id=data["triple_id"],
                    source_entity_id=data["source_entity_id"],
                    target_entity_id=data["target_entity_id"],
                    relation=data.get("relation_type") or data.get("relation") or "RELATED_TO",
                    description=data.get("text") or data.get("description") or "",
                )
                self.db.add(triple)
            else:
                description = data.get("text") or data.get("description") or ""
                if len(description) > len(triple.description):
                    triple.description = description
            for evidence_chunk_id in data.get("chunk_ids") or [chunk_id]:
                self.db.add(
                    KnowledgeGraphTripleMention(
                        knowledge_base_id=knowledge_base_id,
                        document_id=document_id,
                        chunk_id=evidence_chunk_id,
                        triple_id=data["triple_id"],
                    )
                )

        await self.db.commit()

    async def delete_document_graph(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
    ) -> tuple[list[str], list[str]]:
        await self._delete_document_mentions(document_id)
        deleted_entities, deleted_triples = await self._delete_orphans(knowledge_base_id)
        await self.db.commit()
        return deleted_entities, deleted_triples

    async def list_entities(self, knowledge_base_id: int) -> list[KnowledgeGraphEntity]:
        result = await self.db.execute(
            select(KnowledgeGraphEntity).where(
                KnowledgeGraphEntity.knowledge_base_id == knowledge_base_id
            )
        )
        return list(result.scalars().all())

    async def list_triples(self, knowledge_base_id: int) -> list[KnowledgeGraphTriple]:
        result = await self.db.execute(
            select(KnowledgeGraphTriple).where(
                KnowledgeGraphTriple.knowledge_base_id == knowledge_base_id
            )
        )
        return list(result.scalars().all())

    async def count_by_knowledge_base(
        self,
        knowledge_base_id: int,
    ) -> tuple[int, int]:
        entity_count = await self.db.scalar(
            select(func.count(KnowledgeGraphEntity.id)).where(
                KnowledgeGraphEntity.knowledge_base_id == knowledge_base_id
            )
        )
        triple_count = await self.db.scalar(
            select(func.count(KnowledgeGraphTriple.id)).where(
                KnowledgeGraphTriple.knowledge_base_id == knowledge_base_id
            )
        )
        return int(entity_count or 0), int(triple_count or 0)

    async def delete_by_knowledge_base(self, knowledge_base_id: int) -> None:
        await self.db.execute(
            delete(KnowledgeGraphTriple).where(
                KnowledgeGraphTriple.knowledge_base_id == knowledge_base_id
            )
        )
        await self.db.execute(
            delete(KnowledgeGraphEntity).where(
                KnowledgeGraphEntity.knowledge_base_id == knowledge_base_id
            )
        )
        await self.db.commit()

    async def list_entity_ids_by_chunk_ids(
        self,
        chunk_ids: list[str],
    ) -> dict[str, list[str]]:
        """查询主召回 chunk 对应的实体，用于补充图检索种子。"""
        if not chunk_ids:
            return {}
        result = await self.db.execute(
            select(
                KnowledgeGraphEntityMention.chunk_id,
                KnowledgeGraphEntityMention.entity_id,
            ).where(KnowledgeGraphEntityMention.chunk_id.in_(chunk_ids))
        )
        mapping: dict[str, list[str]] = {}
        for chunk_id, entity_id in result.all():
            mapping.setdefault(str(chunk_id), []).append(str(entity_id))
        return mapping

    async def _delete_document_mentions(self, document_id: int) -> None:
        await self.db.execute(
            delete(KnowledgeGraphTripleMention).where(
                KnowledgeGraphTripleMention.document_id == document_id
            )
        )
        await self.db.execute(
            delete(KnowledgeGraphEntityMention).where(
                KnowledgeGraphEntityMention.document_id == document_id
            )
        )
        await self.db.flush()

    async def _delete_orphans(self, knowledge_base_id: int) -> tuple[list[str], list[str]]:
        triple_ids = list(
            (
                await self.db.execute(
                    select(KnowledgeGraphTriple.triple_id).where(
                        KnowledgeGraphTriple.knowledge_base_id == knowledge_base_id,
                        ~KnowledgeGraphTriple.triple_id.in_(
                            select(KnowledgeGraphTripleMention.triple_id)
                        ),
                    )
                )
            ).scalars()
        )
        if triple_ids:
            await self.db.execute(
                delete(KnowledgeGraphTriple).where(
                    KnowledgeGraphTriple.triple_id.in_(triple_ids)
                )
            )
            await self.db.flush()

        entity_ids = list(
            (
                await self.db.execute(
                    select(KnowledgeGraphEntity.entity_id).where(
                        KnowledgeGraphEntity.knowledge_base_id == knowledge_base_id,
                        ~KnowledgeGraphEntity.entity_id.in_(
                            select(KnowledgeGraphEntityMention.entity_id)
                        ),
                        ~KnowledgeGraphEntity.entity_id.in_(
                            select(KnowledgeGraphTriple.source_entity_id)
                        ),
                        ~KnowledgeGraphEntity.entity_id.in_(
                            select(KnowledgeGraphTriple.target_entity_id)
                        ),
                    )
                )
            ).scalars()
        )
        if entity_ids:
            await self.db.execute(
                delete(KnowledgeGraphEntity).where(
                    KnowledgeGraphEntity.entity_id.in_(entity_ids)
                )
            )
            await self.db.flush()
        return entity_ids, triple_ids


class EvaluationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_dataset_with_items(
        self,
        dataset_data: dict,
        items_data: list[dict],
    ) -> EvaluationDataset:
        dataset = EvaluationDataset(**dataset_data)
        self.db.add(dataset)
        self.db.add_all([EvaluationDatasetItem(**item) for item in items_data])
        await self.db.commit()
        await self.db.refresh(dataset)
        return dataset

    async def list_datasets(self, knowledge_base_id: int, user_id: str) -> list[EvaluationDataset]:
        result = await self.db.execute(
            select(EvaluationDataset)
            .where(
                EvaluationDataset.knowledge_base_id == knowledge_base_id,
                EvaluationDataset.user_id == user_id,
            )
            .order_by(EvaluationDataset.updated_at.desc(), EvaluationDataset.id.desc())
        )
        return list(result.scalars().all())

    async def get_dataset(self, dataset_id: str) -> EvaluationDataset | None:
        result = await self.db.execute(
            select(EvaluationDataset).where(EvaluationDataset.dataset_id == dataset_id)
        )
        return result.scalar_one_or_none()

    async def list_dataset_items(
        self,
        dataset_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[EvaluationDatasetItem]:
        result = await self.db.execute(
            select(EvaluationDatasetItem)
            .where(EvaluationDatasetItem.dataset_id == dataset_id)
            .order_by(EvaluationDatasetItem.item_index.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def list_all_dataset_items(self, dataset_id: str) -> list[EvaluationDatasetItem]:
        result = await self.db.execute(
            select(EvaluationDatasetItem)
            .where(EvaluationDatasetItem.dataset_id == dataset_id)
            .order_by(EvaluationDatasetItem.item_index.asc())
        )
        return list(result.scalars().all())

    async def count_dataset_items(self, dataset_id: str) -> int:
        result = await self.db.execute(
            select(func.count(EvaluationDatasetItem.id)).where(EvaluationDatasetItem.dataset_id == dataset_id)
        )
        return int(result.scalar() or 0)

    async def delete_dataset(self, dataset: EvaluationDataset) -> None:
        await self.db.delete(dataset)
        await self.db.commit()

    async def create_run(self, data: dict) -> EvaluationRun:
        run = EvaluationRun(**data)
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def get_run(self, run_id: str) -> EvaluationRun | None:
        result = await self.db.execute(select(EvaluationRun).where(EvaluationRun.run_id == run_id))
        return result.scalar_one_or_none()

    async def list_runs(self, knowledge_base_id: int, user_id: str) -> list[EvaluationRun]:
        result = await self.db.execute(
            select(EvaluationRun)
            .where(
                EvaluationRun.knowledge_base_id == knowledge_base_id,
                EvaluationRun.user_id == user_id,
            )
            .order_by(EvaluationRun.started_at.desc(), EvaluationRun.id.desc())
        )
        return list(result.scalars().all())

    async def update_run(self, run: EvaluationRun, data: dict) -> EvaluationRun:
        for key, value in data.items():
            setattr(run, key, value)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def upsert_run_item(self, run_id: str, item_index: int, data: dict) -> EvaluationRunItem:
        result = await self.db.execute(
            select(EvaluationRunItem).where(
                EvaluationRunItem.run_id == run_id,
                EvaluationRunItem.item_index == item_index,
            )
        )
        item = result.scalar_one_or_none()
        if item is None:
            item = EvaluationRunItem(run_id=run_id, item_index=item_index, **data)
            self.db.add(item)
        else:
            for key, value in data.items():
                setattr(item, key, value)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def list_run_items(
        self,
        run_id: str,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[EvaluationRunItem]:
        result = await self.db.execute(
            select(EvaluationRunItem)
            .where(EvaluationRunItem.run_id == run_id)
            .order_by(EvaluationRunItem.item_index.asc())
            .offset(offset)
            .limit(limit)
        )
        return list(result.scalars().all())

    async def count_run_items(self, run_id: str) -> int:
        result = await self.db.execute(
            select(func.count(EvaluationRunItem.id)).where(EvaluationRunItem.run_id == run_id)
        )
        return int(result.scalar() or 0)

    async def delete_run(self, run: EvaluationRun) -> None:
        await self.db.delete(run)
        await self.db.commit()


class ConversationRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list(self, user_id: str, include_archived: bool = False) -> list[Conversation]:
        stmt = (
            select(Conversation)
            .where(Conversation.user_id == user_id)
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        )
        if not include_archived:
            stmt = stmt.where(Conversation.archived.is_(False))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get(self, conversation_id: int, user_id: str | None = None) -> Conversation | None:
        stmt = select(Conversation).where(Conversation.id == conversation_id)
        if user_id is not None:
            stmt = stmt.where(Conversation.user_id == user_id)
        result = await self.db.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, user_id: str, title: str = "新对话") -> Conversation:
        item = Conversation(user_id=user_id, title=title)
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


class AgentRunRepository:
    """Database operations for parent and child agent executions."""

    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(self, data: dict) -> AgentRun:
        item = AgentRun(**data)
        self.db.add(item)
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def get_by_request_id(self, request_id: str) -> AgentRun | None:
        result = await self.db.execute(select(AgentRun).where(AgentRun.request_id == request_id))
        return result.scalar_one_or_none()

    async def get(self, run_id: str, *, user_id: str | None = None) -> AgentRun | None:
        """Load one run, optionally restricting it to its owner."""
        statement = select(AgentRun).where(AgentRun.id == run_id)
        if user_id is not None:
            statement = statement.where(AgentRun.user_id == user_id)
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()

    async def get_active_chat_run(self, *, conversation_id: int, user_id: str) -> AgentRun | None:
        """Return the latest unfinished parent chat run for one conversation."""
        result = await self.db.execute(
            select(AgentRun)
            .where(
                AgentRun.conversation_id == conversation_id,
                AgentRun.user_id == user_id,
                AgentRun.run_type == "chat",
                AgentRun.parent_agent_run_id.is_(None),
                AgentRun.status.in_(["pending", "running"]),
            )
            .order_by(AgentRun.created_at.desc())
        )
        return result.scalars().first()

    async def list_chat_runs_by_status(self, statuses: list[str]) -> list[AgentRun]:
        """List parent chat runs used by startup recovery."""
        result = await self.db.execute(
            select(AgentRun).where(
                AgentRun.run_type == "chat",
                AgentRun.parent_agent_run_id.is_(None),
                AgentRun.status.in_(statuses),
            )
        )
        return list(result.scalars().all())

    async def set_status(self, run_id: str, status: str) -> AgentRun:
        """Update a non-terminal run status without setting finished_at."""
        item = await self.get(run_id)
        if item is None:
            raise ValueError("Agent run not found.")
        item.status = status
        await self.db.commit()
        await self.db.refresh(item)
        return item

    async def get_latest_subagent_for_thread(
        self,
        *,
        thread_id: str,
        user_id: str,
    ) -> AgentRun | None:
        result = await self.db.execute(
            select(AgentRun)
            .where(
                AgentRun.thread_id == thread_id,
                AgentRun.user_id == user_id,
                AgentRun.run_type == "subagent",
            )
            .order_by(AgentRun.created_at.desc())
        )
        return result.scalars().first()

    async def list_checkpoint_thread_ids(
        self,
        *,
        conversation_id: int,
        user_id: str,
    ) -> list[str]:
        """Return every persisted LangGraph thread owned by one conversation."""
        result = await self.db.execute(
            select(AgentRun.checkpoint_thread_id)
            .where(
                AgentRun.conversation_id == conversation_id,
                AgentRun.user_id == user_id,
                AgentRun.checkpoint_thread_id.is_not(None),
            )
            .distinct()
        )
        return [thread_id for thread_id in result.scalars().all() if thread_id]

    async def set_terminal_status(
        self,
        run_id: str,
        *,
        status: str,
        result_payload: dict | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> AgentRun:
        result = await self.db.execute(select(AgentRun).where(AgentRun.id == run_id))
        item = result.scalar_one()
        item.status = status
        # Existing project DateTime columns are timezone-naive; store UTC consistently.
        item.finished_at = datetime.utcnow()
        if result_payload is not None:
            item.result_payload = result_payload
        item.error_type = error_type
        item.error_message = error_message
        await self.db.commit()
        await self.db.refresh(item)
        return item
