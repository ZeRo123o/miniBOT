from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from pymilvus import DataType, Function, FunctionType, MilvusClient

from app.core.config import get_settings
from app.knowledge.embedding import get_embedding_service
from app.knowledge.graphs.graph_utils import (
    graph_entity_collection_name,
    graph_triple_collection_name,
)
from app.knowledge.backends.milvus import (
    CONTENT_ANALYZER_PARAMS,
    CONTENT_SPARSE_FIELD,
    VECTOR_METRIC_TYPE,
    run_milvus_io,
)

logger = logging.getLogger(__name__)


class MilvusGraphVectorStore:
    """为每个知识库维护实体与三元组两套 Milvus 向量集合。"""

    def __init__(self) -> None:
        settings = get_settings()
        self.milvus_uri = settings.milvus_uri
        self.milvus_token = settings.milvus_token
        self.milvus_db = settings.milvus_db
        self._client: MilvusClient | None = None

    async def insert_missing_graph_records(
        self,
        *,
        kb_id: str,
        embedding_model_spec: str,
        entities: list[dict[str, Any]],
        triples: list[dict[str, Any]],
    ) -> None:
        """只向量化并插入尚未存在的实体和三元组。"""
        if not entities and not triples:
            return

        embedding_service = get_embedding_service(embedding_model_spec)
        entity_collection = await run_milvus_io(
            self._get_or_create_entity_collection,
            kb_id,
            embedding_service.dimension,
            embedding_service.model_name,
        )
        triple_collection = await run_milvus_io(
            self._get_or_create_triple_collection,
            kb_id,
            embedding_service.dimension,
            embedding_service.model_name,
        )

        entity_ids = [str(entity["entity_id"]) for entity in entities]
        triple_ids = [str(triple["triple_id"]) for triple in triples]
        existing_entity_ids, existing_triple_ids = await asyncio.gather(
            run_milvus_io(self._query_existing_ids, entity_collection, entity_ids),
            run_milvus_io(self._query_existing_ids, triple_collection, triple_ids),
        )
        missing_entities = [
            entity
            for entity in entities
            if str(entity["entity_id"]) not in existing_entity_ids
        ]
        missing_triples = [
            triple
            for triple in triples
            if str(triple["triple_id"]) not in existing_triple_ids
        ]
        if not missing_entities and not missing_triples:
            return

        entity_embeddings, triple_embeddings = await asyncio.gather(
            embedding_service.embed_texts(
                [str(entity["content"]) for entity in missing_entities]
            )
            if missing_entities
            else self._empty_embeddings(),
            embedding_service.embed_texts(
                [str(triple["content"]) for triple in missing_triples]
            )
            if missing_triples
            else self._empty_embeddings(),
        )
        insert_tasks = []
        if missing_entities:
            insert_tasks.append(
                run_milvus_io(
                    self._insert_entities,
                    entity_collection,
                    missing_entities,
                    entity_embeddings,
                )
            )
        if missing_triples:
            insert_tasks.append(
                run_milvus_io(
                    self._insert_triples,
                    triple_collection,
                    missing_triples,
                    triple_embeddings,
                )
            )
        if insert_tasks:
            await asyncio.gather(*insert_tasks)

    async def delete_graph_records(
        self,
        kb_id: str,
        *,
        entity_ids: list[str],
        triple_ids: list[str],
    ) -> None:
        tasks = []
        if entity_ids:
            tasks.append(
                run_milvus_io(
                    self._delete_ids,
                    graph_entity_collection_name(kb_id),
                    entity_ids,
                )
            )
        if triple_ids:
            tasks.append(
                run_milvus_io(
                    self._delete_ids,
                    graph_triple_collection_name(kb_id),
                    triple_ids,
                )
            )
        if tasks:
            await asyncio.gather(*tasks)

    async def search_entities(
        self,
        *,
        kb_id: str,
        query_text: str,
        embedding_model_spec: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        collection_name = graph_entity_collection_name(kb_id)
        if not await run_milvus_io(self._has_collection, collection_name):
            return []
        return await self._search_graph_collection(
            collection_name=collection_name,
            query_text=query_text,
            embedding_model_spec=embedding_model_spec,
            top_k=top_k,
            output_fields=["id", "content"],
        )

    async def search_triples(
        self,
        *,
        kb_id: str,
        query_text: str,
        embedding_model_spec: str,
        top_k: int,
    ) -> list[dict[str, Any]]:
        collection_name = graph_triple_collection_name(kb_id)
        if not await run_milvus_io(self._has_collection, collection_name):
            return []
        return await self._search_graph_collection(
            collection_name=collection_name,
            query_text=query_text,
            embedding_model_spec=embedding_model_spec,
            top_k=top_k,
            output_fields=["id", "content", "source_id", "target_id"],
        )

    def drop_graph_collections(self, kb_id: str) -> None:
        client = self._connect()
        for collection_name in (
            graph_entity_collection_name(kb_id),
            graph_triple_collection_name(kb_id),
        ):
            try:
                if client.has_collection(collection_name=collection_name):
                    client.drop_collection(collection_name=collection_name)
                    logger.info("Milvus 图集合已删除：%s", collection_name)
            except Exception as error:
                logger.error("Milvus 图集合删除失败：%s，错误：%s", collection_name, error)

    async def close(self) -> None:
        """应用关闭时释放客户端；这是当前项目生命周期需要的补充接口。"""
        if self._client is not None:
            await run_milvus_io(self._client.close)
            self._client = None

    @staticmethod
    async def _empty_embeddings() -> list[list[float]]:
        return []

    async def _search_graph_collection(
        self,
        *,
        collection_name: str,
        query_text: str,
        embedding_model_spec: str,
        top_k: int,
        output_fields: list[str],
    ) -> list[dict[str, Any]]:
        if top_k <= 0:
            return []
        embedding_service = get_embedding_service(embedding_model_spec)
        query_embedding = await embedding_service.embed_texts([query_text])
        return await run_milvus_io(
            self._search_loaded_collection,
            collection_name,
            query_embedding,
            max(top_k, 1),
            output_fields,
        )

    def _search_loaded_collection(
        self,
        collection_name: str,
        query_embedding: list[list[float]],
        top_k: int,
        output_fields: list[str],
    ) -> list[dict[str, Any]]:
        client = self._connect()
        client.load_collection(collection_name=collection_name)
        results = client.search(
            collection_name=collection_name,
            data=query_embedding,
            anns_field="embedding",
            search_params={
                "metric_type": VECTOR_METRIC_TYPE,
                "params": {"nprobe": 10},
            },
            limit=top_k,
            output_fields=output_fields,
        )
        if not results or not results[0]:
            return []
        records = []
        for hit in results[0]:
            row = hit.get("entity") or {}
            record = {field: row.get(field) for field in output_fields}
            record["score"] = float(hit.get("distance") or 0.0)
            records.append(record)
        return records

    def _get_or_create_entity_collection(
        self,
        kb_id: str,
        dimension: int,
        model_name: str,
    ) -> str:
        return self._get_or_create_collection(
            collection_name=graph_entity_collection_name(kb_id),
            dimension=dimension,
            model_name=model_name,
            include_endpoints=False,
        )

    def _get_or_create_triple_collection(
        self,
        kb_id: str,
        dimension: int,
        model_name: str,
    ) -> str:
        return self._get_or_create_collection(
            collection_name=graph_triple_collection_name(kb_id),
            dimension=dimension,
            model_name=model_name,
            include_endpoints=True,
        )

    def _get_or_create_collection(
        self,
        *,
        collection_name: str,
        dimension: int,
        model_name: str,
        include_endpoints: bool,
    ) -> str:
        client = self._connect()
        if client.has_collection(collection_name=collection_name):
            return collection_name

        schema = MilvusClient.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
            description=(
                f"Knowledge graph collection {collection_name} using {model_name}"
            ),
        )
        schema.add_field(
            field_name="id",
            datatype=DataType.VARCHAR,
            max_length=100,
            is_primary=True,
        )
        schema.add_field(
            field_name="content",
            datatype=DataType.VARCHAR,
            max_length=65535,
            enable_analyzer=True,
            analyzer_params=CONTENT_ANALYZER_PARAMS,
        )
        if include_endpoints:
            schema.add_field(
                field_name="source_id",
                datatype=DataType.VARCHAR,
                max_length=100,
            )
            schema.add_field(
                field_name="target_id",
                datatype=DataType.VARCHAR,
                max_length=100,
            )
        schema.add_field(
            field_name="embedding",
            datatype=DataType.FLOAT_VECTOR,
            dim=dimension,
        )
        schema.add_field(
            field_name=CONTENT_SPARSE_FIELD,
            datatype=DataType.SPARSE_FLOAT_VECTOR,
        )
        schema.add_function(
            Function(
                name="content_bm25",
                function_type=FunctionType.BM25,
                input_field_names=["content"],
                output_field_names=[CONTENT_SPARSE_FIELD],
            )
        )

        indexes = MilvusClient.prepare_index_params()
        indexes.add_index(
            field_name="embedding",
            index_type="IVF_FLAT",
            metric_type=VECTOR_METRIC_TYPE,
            params={"nlist": 1024},
        )
        indexes.add_index(
            field_name=CONTENT_SPARSE_FIELD,
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
            params={"inverted_index_algo": "DAAT_MAXSCORE"},
        )
        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=indexes,
        )
        return collection_name

    def _query_existing_ids(
        self,
        collection_name: str,
        ids: list[str],
    ) -> set[str]:
        if not ids:
            return set()
        client = self._connect()
        client.load_collection(collection_name=collection_name)
        existing_ids: set[str] = set()
        for start in range(0, len(ids), 1000):
            batch = ids[start : start + 1000]
            rows = client.query(
                collection_name=collection_name,
                filter=f"id in {json.dumps(batch, ensure_ascii=False)}",
                output_fields=["id"],
            )
            existing_ids.update(str(row["id"]) for row in rows)
        return existing_ids

    def _insert_entities(
        self,
        collection_name: str,
        entities: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        if len(entities) != len(embeddings):
            raise ValueError("实体记录数与向量数不一致")
        client = self._connect()
        client.insert(
            collection_name=collection_name,
            data=[
                {
                    "id": str(entity["entity_id"]),
                    "content": str(entity["content"]),
                    "embedding": embedding,
                }
                for entity, embedding in zip(entities, embeddings, strict=True)
            ],
        )
        client.flush(collection_name=collection_name)

    def _insert_triples(
        self,
        collection_name: str,
        triples: list[dict[str, Any]],
        embeddings: list[list[float]],
    ) -> None:
        if len(triples) != len(embeddings):
            raise ValueError("三元组记录数与向量数不一致")
        client = self._connect()
        client.insert(
            collection_name=collection_name,
            data=[
                {
                    "id": str(triple["triple_id"]),
                    "content": str(triple["content"]),
                    "source_id": str(triple["source_entity_id"]),
                    "target_id": str(triple["target_entity_id"]),
                    "embedding": embedding,
                }
                for triple, embedding in zip(triples, embeddings, strict=True)
            ],
        )
        client.flush(collection_name=collection_name)

    def _delete_ids(self, collection_name: str, ids: list[str]) -> None:
        client = self._connect()
        if not client.has_collection(collection_name=collection_name):
            return
        for start in range(0, len(ids), 1000):
            batch = ids[start : start + 1000]
            client.delete(
                collection_name=collection_name,
                filter=f"id in {json.dumps(batch, ensure_ascii=False)}",
            )

    def _has_collection(self, collection_name: str) -> bool:
        return bool(self._connect().has_collection(collection_name=collection_name))

    def _connect(self) -> MilvusClient:
        if self._client is not None:
            return self._client
        self._client = MilvusClient(uri=self.milvus_uri, token=self.milvus_token)
        try:
            databases = self._client.list_databases()
            if self.milvus_db not in databases:
                self._client.create_database(db_name=self.milvus_db)
            self._client.use_database(db_name=self.milvus_db)
        except Exception as error:
            logger.warning("Milvus 图数据库切换失败，继续使用默认数据库：%s", error)
        return self._client
