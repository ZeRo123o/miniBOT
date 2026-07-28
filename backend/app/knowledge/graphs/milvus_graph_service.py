from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.repositories import (
    KnowledgeBaseRepository,
    KnowledgeChunkRepository,
    KnowledgeGraphRepository,
)
from app.knowledge.graphs.extractors import (
    GraphExtractorFactory,
    normalize_extraction_result,
)
from app.knowledge.graphs.graph_utils import (
    build_graph_payload,
    compute_entity_id,
    compute_triple_id,
    cypher_merge_chunk,
    cypher_merge_entity_mention,
    cypher_merge_relation,
    normalize_entity_name,
)
from app.knowledge.graphs.milvus_graph_vector_store import MilvusGraphVectorStore
from app.knowledge.backends.milvus import run_milvus_io
from app.storage.neo4j import (
    Neo4jConnectionManager,
    close_shared_neo4j_connection,
    get_shared_neo4j_connection,
    safe_neo4j_label,
)

logger = logging.getLogger(__name__)

GRAPH_CONFIG_KEY = "graph_build_config"
GRAPH_TASK_TYPE = "knowledge_graph_index"
_graph_write_locks: dict[int, asyncio.Lock] = {}
_graph_vector_store: MilvusGraphVectorStore | None = None


def _get_graph_vector_store() -> MilvusGraphVectorStore:
    global _graph_vector_store
    if _graph_vector_store is None:
        _graph_vector_store = MilvusGraphVectorStore()
    return _graph_vector_store


async def close_graph_resources() -> None:
    """关闭延迟创建的 Neo4j 与 Milvus 客户端。"""
    global _graph_vector_store
    await close_shared_neo4j_connection()
    if _graph_vector_store is not None:
        await _graph_vector_store.close()
        _graph_vector_store = None
    _graph_write_locks.clear()


class MilvusGraphService:
    """编排图抽取、PG 元数据、Neo4j 拓扑和 Milvus 图向量索引。"""

    def __init__(
        self,
        db: AsyncSession,
        *,
        kb_id: str | None = None,
        kb_repo: KnowledgeBaseRepository | None = None,
        chunk_repo: KnowledgeChunkRepository | None = None,
        graph_repo: KnowledgeGraphRepository | None = None,
        graph_vector_store: MilvusGraphVectorStore | None = None,
        neo4j_connection: Neo4jConnectionManager | None = None,
    ):
        self.kb_id = kb_id
        self.kb_repo = kb_repo or KnowledgeBaseRepository(db)
        self.chunk_repo = chunk_repo or KnowledgeChunkRepository(db)
        self.repo = graph_repo or KnowledgeGraphRepository(db)
        self._connection = neo4j_connection
        self._schema_initialized = False
        self._graph_vector_store = graph_vector_store

    @property
    def connection(self) -> Neo4jConnectionManager:
        if self._connection is None:
            self._connection = get_shared_neo4j_connection()
        return self._connection

    @property
    def graph_vector_store(self) -> MilvusGraphVectorStore:
        if self._graph_vector_store is None:
            self._graph_vector_store = _get_graph_vector_store()
        return self._graph_vector_store

    @property
    def driver(self):
        return self.connection.driver

    async def _ensure_neo4j_schema(self) -> None:
        """为稳定业务 ID 建立唯一约束；同一服务实例只检查一次。"""
        if self._schema_initialized:
            return
        async with self.driver.session() as session:
            for label, field in (("Chunk", "chunk_id"), ("Entity", "entity_id")):
                await session.run(
                    f"CREATE CONSTRAINT {label.lower()}_{field}_unique IF NOT EXISTS "
                    f"FOR (n:{label}) REQUIRE n.{field} IS UNIQUE"
                )
        self._schema_initialized = True

    @staticmethod
    async def _delete_orphan_entities(transaction: Any, kb_id: str) -> None:
        await transaction.run(
            """
            MATCH (e:Entity:MilvusKB {kb_id: $kb_id})
            WHERE NOT (:Chunk:MilvusKB)-[:MENTIONS]->(e)
            DETACH DELETE e
            """,
            kb_id=kb_id,
        )
    async def _write_chunk_to_neo4j(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        chunk: dict[str, Any],
        entities: list[dict[str, Any]],
        triples: list[dict[str, Any]],
    ) -> None:
        """增量写入一个 Chunk，不影响同一文档已经建立的其他子图。"""
        await self._ensure_neo4j_schema()
        kb_id = str(knowledge_base_id)
        file_id = str(document_id)
        label = safe_neo4j_label(f"kb_{knowledge_base_id}")
        entities_by_id = {entity["entity_id"]: entity for entity in entities}

        async with self.driver.session() as session:
            async with await session.begin_transaction() as transaction:
                await transaction.run(
                    cypher_merge_chunk(label),
                    chunk_id=str(chunk["chunk_id"]),
                    file_id=file_id,
                    kb_id=kb_id,
                    chunk_index=int(chunk.get("chunk_index") or 0),
                    content_preview=str(chunk.get("content") or "")[:500],
                    start_char_pos=int(chunk.get("start_char_pos") or 0),
                    end_char_pos=int(chunk.get("end_char_pos") or 0),
                )
                for entity in entities:
                    await transaction.run(
                        cypher_merge_entity_mention(label),
                        chunk_id=str(chunk["chunk_id"]),
                        file_id=file_id,
                        kb_id=kb_id,
                        normalized_name=entity["normalized_name"],
                        entity_label=entity["entity_type"],
                        entity_id=entity["entity_id"],
                        name=entity["name"],
                        attributes_json=json.dumps(
                            entity.get("attributes") or [],
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    )
                for triple in triples:
                    source = entities_by_id[triple["source_entity_id"]]
                    target = entities_by_id[triple["target_entity_id"]]
                    await transaction.run(
                        cypher_merge_relation(label),
                        kb_id=kb_id,
                        chunk_id=str(chunk["chunk_id"]),
                        file_id=file_id,
                        source_name=source["normalized_name"],
                        source_label=source["entity_type"],
                        target_name=target["normalized_name"],
                        target_label=target["entity_type"],
                        relation_type=triple["relation"],
                        triple_id=triple["triple_id"],
                        text=triple.get("description") or "",
                        extractor_type=triple.get("extractor_type") or "unknown",
                    )

    async def _delete_document_from_neo4j(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
    ) -> None:
        kb_id = str(knowledge_base_id)
        file_id = str(document_id)
        async with self.driver.session() as session:
            async with await session.begin_transaction() as transaction:
                await transaction.run(
                    """
                    MATCH ()-[r:RELATION {kb_id: $kb_id, file_id: $file_id}]->()
                    DELETE r
                    """,
                    kb_id=kb_id,
                    file_id=file_id,
                )
                await transaction.run(
                    """
                    MATCH (c:Chunk:MilvusKB {kb_id: $kb_id, file_id: $file_id})
                    DETACH DELETE c
                    """,
                    kb_id=kb_id,
                    file_id=file_id,
                )
                await self._delete_orphan_entities(transaction, kb_id)

    async def _delete_knowledge_base_from_neo4j(
        self,
        knowledge_base_id: int,
    ) -> None:
        async with self.driver.session() as session:
            await session.run(
                "MATCH (n:MilvusKB {kb_id: $kb_id}) DETACH DELETE n",
                kb_id=str(knowledge_base_id),
            )

    async def _query_seed_subgraph_from_neo4j(
        self,
        *,
        knowledge_base_id: int,
        entity_ids: list[str],
        max_nodes: int,
    ) -> dict[str, Any]:
        if not entity_ids:
            return {"nodes": [], "edges": []}
        limit = max(1, int(max_nodes))
        async with self.driver.session() as session:
            result = await session.run(
                """
                MATCH (seed:Entity:MilvusKB {kb_id: $kb_id})
                WHERE seed.entity_id IN $entity_ids
                MATCH path = (seed)-[*1..2]-(node:MilvusKB {kb_id: $kb_id})
                WITH path LIMIT $path_limit
                WITH collect(path) AS paths
                UNWIND paths AS node_path
                UNWIND nodes(node_path) AS graph_node
                WITH paths, collect(DISTINCT graph_node) AS all_nodes
                WITH paths, all_nodes[..$max_nodes] AS graph_nodes
                UNWIND paths AS edge_path
                UNWIND relationships(edge_path) AS graph_edge
                WITH graph_nodes, collect(DISTINCT graph_edge) AS candidate_edges
                WITH graph_nodes,
                     [edge IN candidate_edges
                      WHERE startNode(edge) IN graph_nodes
                        AND endNode(edge) IN graph_nodes | edge] AS graph_edges
                RETURN graph_nodes AS nodes, graph_edges AS edges
                """,
                kb_id=str(knowledge_base_id),
                entity_ids=entity_ids,
                max_nodes=limit,
                path_limit=limit * 4,
            )
            record = await result.single()
        if record is None:
            return {"nodes": [], "edges": []}

        nodes = [
            self._normalize_node(node, str(knowledge_base_id))
            for node in record["nodes"] or []
        ]
        nodes = [node for node in nodes if node][:limit]
        node_ids = {node["id"] for node in nodes}
        edges = [
            self._normalize_edge(edge)
            for edge in record["edges"] or []
        ]
        return {
            "nodes": nodes,
            "edges": [
                edge
                for edge in edges
                if edge
                and edge["source_id"] in node_ids
                and edge["target_id"] in node_ids
            ],
        }

    async def _query_nodes_from_neo4j(
        self,
        *,
        knowledge_base_id: int,
        keyword: str,
        max_depth: int,
        max_nodes: int,
        exclude_chunk: bool,
    ) -> dict[str, Any]:
        kb_id = str(knowledge_base_id)
        label = safe_neo4j_label(f"kb_{knowledge_base_id}")
        clauses: list[str] = []
        if exclude_chunk:
            clauses.append("NOT n:Chunk")
        if keyword and keyword != "*":
            clauses.append(
                "(toLower(coalesce(n.name, '')) CONTAINS toLower($keyword) "
                "OR toLower(coalesce(n.content_preview, '')) CONTAINS toLower($keyword) "
                "OR toLower(coalesce(n.chunk_id, '')) CONTAINS toLower($keyword))"
            )
        where = "WHERE " + " AND ".join(clauses) if clauses else ""
        limit = max(1, int(max_nodes))
        if max_depth <= 0:
            cypher = f"""
            MATCH (n:MilvusKB:`{label}`)
            {where}
            RETURN n AS h, null AS r, null AS t
            LIMIT $limit
            """
        else:
            neighbor_filter = " WHERE NOT m:Chunk" if exclude_chunk else ""
            cypher = f"""
            MATCH (n:MilvusKB:`{label}`)
            {where}
            WITH n LIMIT $limit
            OPTIONAL MATCH (n)-[r]-(m:MilvusKB:`{label}`){neighbor_filter}
            RETURN n AS h, r AS r, m AS t
            LIMIT $edge_limit
            """
        async with self.driver.session() as session:
            result = await session.run(
                cypher,
                keyword=keyword,
                limit=limit,
                edge_limit=limit * 10,
            )
            records = [record async for record in result]

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        node_ids: set[str] = set()
        edge_ids: set[str] = set()
        for record in records:
            for key in ("h", "t"):
                raw_node = record.get(key)
                if raw_node is None:
                    continue
                node = self._normalize_node(raw_node, kb_id)
                if (
                    not node
                    or node["id"] in node_ids
                    or (exclude_chunk and node["type"] == "Chunk")
                ):
                    continue
                nodes.append(node)
                node_ids.add(node["id"])
            raw_edge = record.get("r")
            if raw_edge is not None:
                edge = self._normalize_edge(raw_edge)
                if edge and edge["id"] not in edge_ids:
                    edges.append(edge)
                    edge_ids.add(edge["id"])
            if len(nodes) >= limit:
                break
        return {
            "nodes": nodes[:limit],
            "edges": edges[: limit * 2],
        }

    async def _get_labels_from_neo4j(
        self,
        knowledge_base_id: int,
    ) -> list[str]:
        label = safe_neo4j_label(f"kb_{knowledge_base_id}")
        async with self.driver.session() as session:
            result = await session.run(
                f"""
                MATCH (n:MilvusKB:`{label}`)
                UNWIND labels(n) AS node_label
                WITH DISTINCT node_label
                WHERE node_label <> 'MilvusKB' AND node_label <> $db_label
                RETURN node_label
                ORDER BY node_label
                """,
                db_label=label,
            )
            return [record["node_label"] async for record in result]

    async def _get_stats_from_neo4j(
        self,
        knowledge_base_id: int,
    ) -> dict[str, Any]:
        label = safe_neo4j_label(f"kb_{knowledge_base_id}")
        async with self.driver.session() as session:
            stats_result = await session.run(
                f"""
                MATCH (n:MilvusKB:`{label}`)
                WITH count(n) AS node_count
                OPTIONAL MATCH (:MilvusKB:`{label}`)-[r]->(:MilvusKB:`{label}`)
                RETURN node_count, count(r) AS edge_count
                """
            )
            stats = await stats_result.single()
            label_result = await session.run(
                f"""
                MATCH (n:Entity:MilvusKB:`{label}`)
                WITH n.label AS entity_label, count(*) AS count
                RETURN entity_label, count
                ORDER BY count DESC
                """
            )
            entity_types = [
                {"type": record["entity_label"], "count": record["count"]}
                async for record in label_result
            ]
        return {
            "total_nodes": stats["node_count"] if stats else 0,
            "total_edges": stats["edge_count"] if stats else 0,
            "entity_types": entity_types,
        }

    @staticmethod
    def _normalize_node(raw_node: Any, kb_id: str) -> dict[str, Any]:
        if not hasattr(raw_node, "element_id"):
            return {}
        properties = dict(raw_node.items())
        attributes_json = properties.pop("attributes_json", None)
        if isinstance(attributes_json, str):
            try:
                properties["attributes"] = json.loads(attributes_json)
            except json.JSONDecodeError:
                properties["attributes"] = []
        labels = list(raw_node.labels)
        filtered_labels = [
            label
            for label in labels
            if label not in {"MilvusKB", f"kb_{kb_id}"}
        ]
        entity_type = (
            "Chunk"
            if "Chunk" in labels
            else properties.get("label", "Entity")
        )
        name = (
            properties.get("name")
            or properties.get("content_preview")
            or properties.get("chunk_id")
            or "Unknown"
        )
        return {
            "id": raw_node.element_id,
            "name": name,
            "original_id": raw_node.element_id,
            "type": entity_type,
            "labels": filtered_labels,
            "properties": properties,
            "normalized": {
                "name": name,
                "type": entity_type,
                "source": "milvus",
            },
            "graph_type": "milvus",
        }

    @staticmethod
    def _normalize_edge(raw_edge: Any) -> dict[str, Any]:
        if not hasattr(raw_edge, "element_id"):
            return {}
        properties = dict(raw_edge.items())
        return {
            "id": raw_edge.element_id,
            "source_id": raw_edge.start_node.element_id,
            "target_id": raw_edge.end_node.element_id,
            "type": properties.get("type") or raw_edge.type,
            "label": properties.get("type") or raw_edge.type,
            "properties": properties,
        }

    async def get_status(
        self,
        kb_id: str,
    ) -> dict[str, Any]:
        knowledge_base = await self._get_knowledge_base(kb_id)
        metadata = knowledge_base.runtime_metadata()
        config = metadata.get(GRAPH_CONFIG_KEY) or {}
        knowledge_base_id = int(kb_id)
        total_chunks = await self.chunk_repo.count_by_knowledge_base(
            knowledge_base_id
        )
        pending_chunks = await self.chunk_repo.count_graph_pending_by_knowledge_base(
            knowledge_base_id
        )
        indexed_chunks = await self.chunk_repo.count_graph_indexed_by_knowledge_base(
            knowledge_base_id
        )
        entity_count, relationship_count = await self.repo.count_by_knowledge_base(
            knowledge_base_id
        )

        task_state = dict(
            (knowledge_base.additional_params or {}).get("graph_build_task") or {}
        )

        return {
            "kb_id": kb_id,
            "configured": bool(config),
            "locked": bool(config.get("locked")),
            "config": self._public_config(config),
            "total_chunks": total_chunks,
            "pending_chunks": pending_chunks,
            "indexed_chunks": indexed_chunks,
            "entity_count": entity_count,
            "relationship_count": relationship_count,
            "build_task_status": task_state.get("status"),
            "build_task_progress": int(task_state.get("progress") or 0),
            "build_task": task_state or None,
        }

    async def configure(
        self,
        kb_id: str,
        extractor_type: str,
        extractor_options: dict[str, Any],
        created_by: str,
    ) -> dict[str, Any]:
        knowledge_base = await self._get_knowledge_base(kb_id)
        metadata = knowledge_base.runtime_metadata()
        existing_config = metadata.get(GRAPH_CONFIG_KEY) or {}
        normalized_type = str(extractor_type or "").lower()
        if existing_config.get("locked"):
            existing_type = str(existing_config.get("extractor_type") or "").lower()
            if normalized_type != existing_type:
                raise ValueError("图谱抽取器类型已锁定，只能修改模型、Schema 等抽取参数")

        options = dict(extractor_options or {})
        if normalized_type == "llm" and options.get("prompt"):
            raise ValueError(
                "LLM 图谱抽取器不支持自定义完整 Prompt，请使用 schema 配置抽取约束"
            )
        GraphExtractorFactory.create(normalized_type, options)
        now = datetime.now(timezone.utc).isoformat()
        config = {
            "locked": True,
            "extractor_type": normalized_type,
            "extractor_options": options,
            "created_at": existing_config.get("created_at") or now,
            "created_by": existing_config.get("created_by") or created_by,
        }
        if existing_config.get("locked"):
            config["updated_at"] = now
            config["updated_by"] = created_by
        metadata[GRAPH_CONFIG_KEY] = config
        # 同步写入显式模型列，供图向量写入和状态展示复用。
        if options.get("model_spec"):
            metadata["extraction_model_spec"] = options["model_spec"]
        await self.kb_repo.update_metadata(knowledge_base, metadata)
        return config

    async def build_pending_chunks(
        self,
        kb_id: str,
        *,
        batch_size: int,
        context: Any = None,
    ) -> dict[str, Any]:
        """并发抽取待处理 Chunk，并按 Chunk 串行写入三类存储。"""
        knowledge_base = await self._get_knowledge_base(kb_id)
        metadata = knowledge_base.runtime_metadata()
        config = self._get_locked_config(metadata)
        extractor = GraphExtractorFactory.create(
            config["extractor_type"],
            self._runtime_extractor_options(config),
        )
        knowledge_base_id = int(kb_id)
        worker_count = self._get_worker_count(config)
        total_pending = await self.chunk_repo.count_graph_pending_by_knowledge_base(
            knowledge_base_id
        )
        processed = 0
        failed = 0
        failed_chunk_ids: set[str] = set()
        write_lock = _graph_write_locks.setdefault(knowledge_base_id, asyncio.Lock())

        while True:
            if context is not None:
                await context.raise_if_cancelled()
            pending = await self.chunk_repo.list_graph_pending_by_knowledge_base(
                knowledge_base_id,
                max(int(batch_size), 1) + len(failed_chunk_ids),
            )
            pending = [
                chunk
                for chunk in pending
                if str(chunk["chunk_id"]) not in failed_chunk_ids
            ][: max(int(batch_size), 1)]
            if not pending:
                break

            queue: asyncio.Queue[Any] = asyncio.Queue()
            for chunk in pending:
                queue.put_nowait(chunk)

            async def process_chunk(chunk: dict[str, Any]) -> None:
                nonlocal processed, failed
                try:
                    if context is not None:
                        await context.raise_if_cancelled()
                    chunk_id = str(chunk["chunk_id"])
                    document_id = int(chunk["document_id"])
                    should_cache = not bool(chunk.get("extraction_result"))
                    raw_result = chunk.get("extraction_result")
                    if should_cache:
                        raw_result = await extractor.extract(
                            str(chunk["content"]),
                            chunk_metadata={
                                "kb_id": kb_id,
                                "chunk_id": chunk_id,
                                "file_id": str(document_id),
                                "chunk_index": int(chunk["chunk_index"]),
                            },
                        )
                    normalized_result = normalize_extraction_result(
                        raw_result,
                        extractor.extractor_type,
                    )

                    # AsyncSession 不能被并发使用，因此只并发 LLM 抽取，写入阶段统一串行。
                    async with write_lock:
                        if should_cache:
                            await self.chunk_repo.update_extraction_result(
                                chunk_id,
                                normalized_result,
                            )
                        entities, triples = await self.write_chunk_graph(
                            kb_id,
                            chunk,
                            normalized_result,
                        )
                        await self.repo.upsert_chunk_graph(
                            knowledge_base_id=knowledge_base_id,
                            document_id=document_id,
                            chunk_id=chunk_id,
                            entities=entities,
                            triples=triples,
                        )
                        await self.graph_vector_store.insert_missing_graph_records(
                            kb_id=kb_id,
                            embedding_model_spec=str(
                                metadata.get("embedding_model_spec") or ""
                            ),
                            entities=entities,
                            triples=triples,
                        )
                        await self.chunk_repo.mark_graph_indexed(
                            chunk_id,
                            ent_ids=[str(item["entity_id"]) for item in entities],
                        )
                    processed += 1
                except Exception as error:
                    logger.error(
                        "Chunk 图构建失败 chunk_id=%s error=%s",
                        chunk.get("chunk_id"),
                        error,
                    )
                    failed_chunk_ids.add(str(chunk.get("chunk_id")))
                    failed += 1

                if context is not None:
                    completed = processed + failed
                    progress = 5.0 + min(
                        90.0,
                        completed / max(total_pending, 1) * 90.0,
                    )
                    await context.set_progress(
                        progress,
                        f"图构建 {completed}/{total_pending}，失败 {failed}",
                    )

            async def worker() -> None:
                while True:
                    try:
                        chunk = queue.get_nowait()
                    except asyncio.QueueEmpty:
                        return
                    try:
                        await process_chunk(chunk)
                    finally:
                        queue.task_done()

            await asyncio.gather(
                *(worker() for _ in range(min(worker_count, len(pending))))
            )

        remaining = await self.chunk_repo.count_graph_pending_by_knowledge_base(
            knowledge_base_id
        )
        return {
            "kb_id": kb_id,
            "success": processed,
            "failed": failed,
            "remaining": remaining,
        }

    @staticmethod
    def _get_worker_count(config: dict[str, Any]) -> int:
        if str(config.get("extractor_type") or "").lower() != "llm":
            return 1
        try:
            count = int(
                (config.get("extractor_options") or {}).get("concurrency_count")
                or 1
            )
        except (TypeError, ValueError):
            return 1
        return max(1, min(count, 1000))

    @staticmethod
    def _runtime_extractor_options(config: dict[str, Any]) -> dict[str, Any]:
        options = dict(config.get("extractor_options") or {})
        options.pop("prompt", None)
        return options

    async def write_chunk_graph(
        self,
        kb_id: str,
        chunk: dict[str, Any],
        normalized_result: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        """将单个 chunk 的标准化结果增量写入 Neo4j。"""
        payload = build_graph_payload(normalized_result)
        entity_records = self._build_entity_records(kb_id, payload["entities"])
        record_by_local_id = {
            entity["id"]: record
            for entity, record in zip(
                payload["entities"],
                entity_records,
                strict=True,
            )
        }
        triple_records = self._build_triple_records(
            kb_id,
            payload,
            record_by_local_id,
        )
        storage_entities = [
            {
                "entity_id": record["entity_id"],
                "name": record["name"],
                "normalized_name": record["normalized_name"],
                "entity_type": record["label"],
                "description": "\n".join(
                    f"{attribute['label']}：{attribute['text']}"
                    for attribute in record["attributes"]
                ),
                "attributes": record["attributes"],
                "chunk_ids": [str(chunk["chunk_id"])],
            }
            for record in entity_records
        ]
        storage_triples = [
            {
                "triple_id": record["triple_id"],
                "source_entity_id": record["source_entity_id"],
                "target_entity_id": record["target_entity_id"],
                "relation": record["relation_type"],
                "description": record["text"],
                "extractor_type": record["extractor_type"],
                "chunk_ids": [str(chunk["chunk_id"])],
            }
            for record in triple_records
        ]
        await self._write_chunk_to_neo4j(
            knowledge_base_id=int(kb_id),
            document_id=int(chunk["document_id"]),
            chunk=chunk,
            entities=storage_entities,
            triples=storage_triples,
        )
        return entity_records, triple_records

    @staticmethod
    def _build_entity_records(
        kb_id: str,
        entities: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records = []
        for entity in entities:
            label = entity.get("label") or "Entity"
            normalized_name = normalize_entity_name(entity["text"])
            records.append(
                {
                    "entity_id": compute_entity_id(
                        kb_id,
                        normalized_name,
                        label,
                    ),
                    "kb_id": kb_id,
                    "normalized_name": normalized_name,
                    "label": label,
                    "name": entity["text"],
                    "attributes": entity.get("attributes") or [],
                    "content": (
                        f"{entity['text']} ({label}) "
                        f"{entity.get('attributes') or []}"
                    ),
                }
            )
        return records

    @staticmethod
    def _build_triple_records(
        kb_id: str,
        graph_payload: dict[str, Any],
        entity_record_by_local_id: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        records = []
        seen_ids: set[str] = set()
        extractor_type = graph_payload["metadata"].get(
            "extractor_type",
            "unknown",
        )
        for relation in graph_payload["relations"]:
            source = entity_record_by_local_id[relation["source"]]
            target = entity_record_by_local_id[relation["target"]]
            relation_type = relation.get("label") or "RELATED_TO"
            triple_id = compute_triple_id(
                kb_id,
                source["normalized_name"],
                source["label"],
                relation_type,
                target["normalized_name"],
                target["label"],
            )
            if triple_id in seen_ids:
                continue
            seen_ids.add(triple_id)
            records.append(
                {
                    "triple_id": triple_id,
                    "kb_id": kb_id,
                    "source_entity_id": source["entity_id"],
                    "target_entity_id": target["entity_id"],
                    "relation_type": relation_type,
                    "content": (
                        f"{source['normalized_name']} → {relation_type} → "
                        f"{target['normalized_name']}"
                    ),
                    "text": relation["text"],
                    "extractor_type": extractor_type,
                }
            )
        return records

    async def delete_document(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        metadata: dict[str, Any],
    ) -> None:
        async with _graph_write_locks.setdefault(knowledge_base_id, asyncio.Lock()):
            await self._delete_document_from_neo4j(
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
            )
            deleted_entity_ids, deleted_triple_ids = await self.repo.delete_document_graph(
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
            )
            await self.graph_vector_store.delete_graph_records(
                str(knowledge_base_id),
                entity_ids=deleted_entity_ids,
                triple_ids=deleted_triple_ids,
            )

    async def delete_knowledge_base(self, knowledge_base_id: int) -> None:
        async with _graph_write_locks.setdefault(knowledge_base_id, asyncio.Lock()):
            await self._delete_knowledge_base_from_neo4j(knowledge_base_id)
            await run_milvus_io(
                self.graph_vector_store.drop_graph_collections,
                str(knowledge_base_id),
            )
        _graph_write_locks.pop(knowledge_base_id, None)

    async def reset(
        self,
        kb_id: str,
        *,
        clear_extraction_result: bool,
        clear_config: bool,
    ) -> dict[str, Any]:
        knowledge_base = await self._get_knowledge_base(kb_id)
        knowledge_base_id = int(kb_id)
        await self.delete_graph(kb_id)
        await self.repo.delete_by_knowledge_base(knowledge_base_id)
        reset_chunks = await self.chunk_repo.reset_graph_state_by_knowledge_base(
            knowledge_base_id,
            clear_extraction_result,
        )
        metadata = knowledge_base.runtime_metadata()
        metadata.pop("graph_build_task", None)
        if clear_config:
            metadata.pop(GRAPH_CONFIG_KEY, None)
            metadata["extraction_model_spec"] = None
        await self.kb_repo.update_metadata(knowledge_base, metadata)
        return {
            "message": "图谱构建状态已重置",
            "status": "success",
            "reset_chunks": reset_chunks,
            "clear_extraction_result": clear_extraction_result,
            "clear_config": clear_config,
        }

    async def delete_graph(self, kb_id: str) -> None:
        knowledge_base_id = int(kb_id)
        await self._delete_knowledge_base_from_neo4j(knowledge_base_id)
        await run_milvus_io(
            self.graph_vector_store.drop_graph_collections,
            kb_id,
        )

    async def delete_file_graph(self, kb_id: str, file_id: str) -> None:
        await self.delete_document(
            knowledge_base_id=int(kb_id),
            document_id=int(file_id),
            metadata={},
        )

    async def query_nodes(
        self,
        kb_id: str | None = None,
        *,
        keyword: str = "",
        max_depth: int = 1,
        max_nodes: int = 50,
        exclude_chunk: bool = False,
    ) -> dict[str, Any]:
        effective_kb_id = kb_id or self.kb_id
        if not effective_kb_id:
            return {"nodes": [], "edges": []}
        try:
            return await self._query_nodes_from_neo4j(
                knowledge_base_id=int(effective_kb_id),
                keyword=keyword,
                max_depth=max_depth,
                max_nodes=max_nodes,
                exclude_chunk=exclude_chunk,
            )
        except Exception as error:
            logger.error("Milvus 图查询失败：%s", error)
            return {"nodes": [], "edges": []}

    async def query_seed_subgraph(
        self,
        kb_id: str,
        *,
        entity_ids: list[str],
        max_nodes: int,
    ) -> dict[str, Any]:
        if not entity_ids:
            return {"nodes": [], "edges": []}
        try:
            return await self._query_seed_subgraph_from_neo4j(
                knowledge_base_id=int(kb_id),
                entity_ids=list(dict.fromkeys(entity_ids)),
                max_nodes=max_nodes,
            )
        except Exception as error:
            logger.error("Milvus 种子子图查询失败：%s", error)
            return {"nodes": [], "edges": []}

    async def query_and_rank_chunks_by_ppr(
        self,
        kb_id: str,
        seed_weights: dict[str, float],
        *,
        max_nodes: int,
        top_k: int,
        damping: float,
    ) -> list[tuple[str, float]]:
        if not seed_weights:
            return []
        subgraph = await self.query_seed_subgraph(
            kb_id,
            entity_ids=list(seed_weights),
            max_nodes=max_nodes,
        )
        return self.rank_chunks_by_ppr(
            subgraph,
            seed_weights,
            top_k=top_k,
            damping=damping,
        )

    async def get_labels(self, kb_id: str | None = None) -> list[str]:
        effective_kb_id = kb_id or self.kb_id
        if not effective_kb_id:
            return []
        try:
            return await self._get_labels_from_neo4j(int(effective_kb_id))
        except Exception as error:
            logger.error("Milvus 图标签查询失败：%s", error)
            return []

    async def get_stats(self, kb_id: str | None = None) -> dict[str, Any]:
        effective_kb_id = kb_id or self.kb_id
        if not effective_kb_id:
            return {
                "total_nodes": 0,
                "total_edges": 0,
                "entity_types": [],
            }
        try:
            return await self._get_stats_from_neo4j(int(effective_kb_id))
        except Exception as error:
            logger.error("Milvus 图统计查询失败：%s", error)
            return {
                "total_nodes": 0,
                "total_edges": 0,
                "entity_types": [],
            }

    async def search(
        self,
        *,
        knowledge_base_id: int,
        query: str,
        base_chunks: list[dict[str, Any]],
        metadata: dict[str, Any],
        entity_top_k: int,
        triple_top_k: int,
        graph_top_k: int,
        graph_max_nodes: int,
        ppr_damping: float,
        document_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        # 主召回完成后，实体与三元组向量检索在图阶段内部并行。
        embedding_model_spec = str(metadata.get("embedding_model_spec") or "")
        entity_hits, triple_hits = await asyncio.gather(
            self.graph_vector_store.search_entities(
                kb_id=str(knowledge_base_id),
                query_text=query,
                embedding_model_spec=embedding_model_spec,
                top_k=entity_top_k,
            ),
            self.graph_vector_store.search_triples(
                kb_id=str(knowledge_base_id),
                query_text=query,
                embedding_model_spec=embedding_model_spec,
                top_k=triple_top_k,
            ),
        )
        seed_weights = await self._build_seed_weights(
            base_chunks=base_chunks,
            entity_hits=entity_hits,
            triple_hits=triple_hits,
        )
        if not seed_weights:
            return []

        subgraph = await self._query_seed_subgraph_from_neo4j(
            knowledge_base_id=knowledge_base_id,
            entity_ids=list(seed_weights),
            max_nodes=graph_max_nodes,
        )
        allowed_chunk_ids = await self._resolve_allowed_chunk_ids(document_ids)
        ranked_chunks = self.rank_chunks_by_ppr(
            subgraph,
            seed_weights,
            top_k=graph_top_k,
            damping=ppr_damping,
            allowed_chunk_ids=allowed_chunk_ids,
        )
        chunks = await self.chunk_repo.list_by_chunk_ids(
            [chunk_id for chunk_id, _ in ranked_chunks]
        )
        chunks_by_id = {chunk.chunk_id: chunk for chunk in chunks}
        results: list[dict[str, Any]] = []
        for chunk_id, graph_score in ranked_chunks:
            chunk = chunks_by_id.get(chunk_id)
            if chunk is None:
                continue
            results.append(
                {
                    "content": chunk.content,
                    "metadata": {
                        "chunk_id": chunk.chunk_id,
                        "knowledge_base_id": chunk.knowledge_base_id,
                        "document_id": chunk.document_id,
                        "chunk_index": chunk.chunk_index,
                    },
                    "score": float(graph_score),
                    "graph_score": float(graph_score),
                    "retrieval_source": "graph",
                }
            )
        return results

    async def _build_seed_weights(
        self,
        *,
        base_chunks: list[dict[str, Any]],
        entity_hits: list[dict[str, Any]],
        triple_hits: list[dict[str, Any]],
    ) -> dict[str, float]:
        """按图向量命中和主召回证据构造归一化的 PPR 重启向量。"""
        seed_weights: dict[str, float] = {}

        def add_seed(entity_id: str | None, score: float, weight: float) -> None:
            if not entity_id:
                return
            contribution = max(float(score or 0.0), 0.0) * weight
            seed_weights[entity_id] = seed_weights.get(entity_id, 0.0) + contribution

        for hit in entity_hits:
            add_seed(hit.get("id"), hit.get("score", 0.0), 1.0)
        for hit in triple_hits:
            add_seed(hit.get("source_id"), hit.get("score", 0.0), 0.8)
            add_seed(hit.get("target_id"), hit.get("score", 0.0), 0.8)

        chunk_scores = {
            str((chunk.get("metadata") or {}).get("chunk_id")): float(
                chunk.get("score") or 0.0
            )
            for chunk in base_chunks
            if (chunk.get("metadata") or {}).get("chunk_id")
        }
        entity_ids_by_chunk = await self.repo.list_entity_ids_by_chunk_ids(
            list(chunk_scores)
        )
        for chunk_id, entity_ids in entity_ids_by_chunk.items():
            for entity_id in entity_ids:
                add_seed(entity_id, chunk_scores.get(chunk_id, 0.0), 0.3)

        total = sum(seed_weights.values())
        if total <= 0:
            return {}
        return {
            entity_id: weight / total
            for entity_id, weight in seed_weights.items()
        }

    async def _resolve_allowed_chunk_ids(
        self,
        document_ids: list[int] | None,
    ) -> set[str] | None:
        if document_ids is None:
            return None
        chunks = []
        for document_id in document_ids:
            chunks.extend(await self.chunk_repo.list_by_document(document_id))
        return {str(chunk.chunk_id) for chunk in chunks}
    async def _get_knowledge_base(self, kb_id: str):
        try:
            knowledge_base_id = int(kb_id)
        except (TypeError, ValueError) as error:
            raise ValueError(f"无效的知识库 ID：{kb_id}") from error
        knowledge_base = await self.kb_repo.get(knowledge_base_id)
        if knowledge_base is None:
            raise ValueError(f"知识库 {kb_id} 不存在")
        return knowledge_base

    @staticmethod
    def _get_locked_config(metadata: dict[str, Any]) -> dict[str, Any]:
        config = metadata.get(GRAPH_CONFIG_KEY) or {}
        if not config.get("locked"):
            raise ValueError("请先确认并锁定图谱抽取配置")
        if not config.get("extractor_type"):
            raise ValueError("图谱抽取配置缺少 extractor_type")
        return config

    def _public_config(
        self,
        config: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not config:
            return None
        return {
            "locked": bool(config.get("locked")),
            "extractor_type": config.get("extractor_type"),
            "extractor_options": self._runtime_extractor_options(config),
            "created_at": config.get("created_at"),
            "created_by": config.get("created_by"),
            "updated_at": config.get("updated_at"),
            "updated_by": config.get("updated_by"),
        }

    @staticmethod
    def rank_chunks_by_ppr(
        subgraph: dict[str, Any],
        seed_weights: dict[str, float],
        *,
        top_k: int,
        damping: float,
        allowed_chunk_ids: set[str] | None = None,
    ) -> list[tuple[str, float]]:
        """在无向两跳子图上执行个性化 PageRank，只返回 chunk 节点。"""
        import igraph as ig

        nodes = subgraph.get("nodes") or []
        edges = subgraph.get("edges") or []
        if not nodes:
            return []
        node_ids = [str(node["id"]) for node in nodes]
        index_by_id = {node_id: index for index, node_id in enumerate(node_ids)}
        edge_indices = [
            (index_by_id[str(edge["source_id"])], index_by_id[str(edge["target_id"])])
            for edge in edges
            if str(edge.get("source_id")) in index_by_id
            and str(edge.get("target_id")) in index_by_id
        ]
        if not edge_indices:
            return []

        graph = ig.Graph(n=len(nodes), edges=edge_indices, directed=False)
        reset = [0.0] * len(nodes)
        chunk_indexes: list[tuple[int, str]] = []
        for index, node in enumerate(nodes):
            labels = set(node.get("labels") or [])
            properties = node.get("properties") or {}
            chunk_id_value = properties.get("chunk_id") or node.get("chunk_id")
            is_chunk = (
                node.get("type") == "Chunk"
                or "Chunk" in labels
                or "KnowledgeChunk" in labels
            )
            if is_chunk and chunk_id_value:
                chunk_id = str(chunk_id_value)
                if allowed_chunk_ids is None or chunk_id in allowed_chunk_ids:
                    chunk_indexes.append((index, chunk_id))
                continue
            entity_id = str(
                properties.get("entity_id") or node.get("entity_id") or ""
            )
            if entity_id in seed_weights:
                reset[index] = float(seed_weights[entity_id])

        reset_total = sum(reset)
        if reset_total <= 0 or not chunk_indexes:
            return []
        scores = graph.personalized_pagerank(
            damping=min(max(float(damping), 0.1), 0.99),
            reset=[value / reset_total for value in reset],
        )
        ranked = sorted(
            (
                (chunk_id, float(scores[index]))
                for index, chunk_id in chunk_indexes
            ),
            key=lambda item: item[1],
            reverse=True,
        )
        return ranked[: max(1, int(top_k))]
