from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymilvus import (
    AnnSearchRequest,
    DataType,
    Function,
    FunctionType,
    MilvusClient,
    WeightedRanker,
)

from app.vectorstores.base import VectorStore

logger = logging.getLogger(__name__)

CONTENT_SPARSE_FIELD = "content_sparse"
CONTENT_ANALYZER_PARAMS = {"type": "chinese"}
VECTOR_METRIC_TYPE = "COSINE"


class MilvusVectorStore(VectorStore):
    """封装知识库 chunk 在 Milvus 中的写入、删除和混合检索操作。"""

    def __init__(
        self,
        *,
        uri: str,
        token: str,
        database: str,
        collection_prefix: str = "kb_",
    ):
        """保存连接配置，并为当前实例分配独立的 Milvus 连接别名。"""
        self.uri = uri
        self.token = token
        self.database = database
        self.collection_prefix = collection_prefix
        self._client: MilvusClient | None = None

    async def upsert_chunks(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
        dimension: int,
    ) -> None:
        """异步写入文档 chunk，阻塞的 Milvus SDK 调用在线程池中执行。"""
        if not chunks:
            return
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk count and embedding count do not match.")

        await asyncio.to_thread(self._upsert_chunks_sync, knowledge_base_id, document_id, chunks, embeddings, dimension)

    async def delete_document_chunks(self, *, knowledge_base_id: int, document_id: int) -> None:
        """异步删除指定文档在 Milvus 中保存的全部 chunk。"""
        await asyncio.to_thread(self._delete_document_chunks_sync, knowledge_base_id, document_id)

    async def delete_knowledge_base(self, *, knowledge_base_id: int) -> None:
        """Drop the collection dedicated to one knowledge base."""
        await asyncio.to_thread(self._delete_knowledge_base_sync, knowledge_base_id)

    async def search_chunks(
        self,
        *,
        knowledge_base_id: int,
        query_text: str,
        query_embedding: list[float],
        search_mode: str,
        final_top_k: int,
        recall_top_k: int,
        similarity_threshold: float,
        bm25_top_k: int,
        vector_weight: float,
        bm25_weight: float,
        bm25_drop_ratio_search: float,
        include_distances: bool,
        document_ids: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """按向量、关键词或混合模式检索 chunk，并返回统一结果结构。"""
        return await asyncio.to_thread(
            self._search_chunks_sync,
            knowledge_base_id,
            query_text,
            query_embedding,
            search_mode,
            final_top_k,
            recall_top_k,
            similarity_threshold,
            bm25_top_k,
            vector_weight,
            bm25_weight,
            bm25_drop_ratio_search,
            include_distances,
            document_ids,
        )

    def _upsert_chunks_sync(
        self,
        knowledge_base_id: int,
        document_id: int,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
        dimension: int,
    ) -> None:
        """同步执行 chunk 覆盖写入，保证同一文档不会残留旧向量。"""
        collection_name = self._get_or_create_collection(knowledge_base_id, dimension)
        self._delete_document_chunks_from_collection(collection_name, document_id)

        # 稀疏向量不需要客户端写入，由 Milvus BM25 Function 根据 content 自动生成。
        rows = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            rows.append(
                {
                    "id": str(chunk["chunk_id"]),
                    "chunk_id": str(chunk["chunk_id"]),
                    "knowledge_base_id": int(knowledge_base_id),
                    "document_id": int(document_id),
                    "chunk_index": int(chunk["chunk_index"]),
                    "content": str(chunk["content"]),
                    "embedding": embedding,
                }
            )

        client = self._connect()
        client.insert(collection_name=collection_name, data=rows)
        client.flush(collection_name=collection_name)
        client.load_collection(collection_name=collection_name)
        logger.info(
            "Milvus chunks upserted: collection=%s document_id=%s chunks=%s",
            collection_name,
            document_id,
            len(rows),
        )

    def _delete_document_chunks_sync(self, knowledge_base_id: int, document_id: int) -> None:
        """同步删除指定文档的 Milvus 数据；collection 不存在时直接返回。"""
        collection_name = self._collection_name(knowledge_base_id)
        client = self._connect()
        if not client.has_collection(collection_name=collection_name):
            return
        self._delete_document_chunks_from_collection(collection_name, document_id)
        client.flush(collection_name=collection_name)

    def _delete_knowledge_base_sync(self, knowledge_base_id: int) -> None:
        collection_name = self._collection_name(knowledge_base_id)
        client = self._connect()
        if client.has_collection(collection_name=collection_name):
            client.drop_collection(collection_name=collection_name)
            logger.info("Milvus knowledge base collection deleted: collection=%s", collection_name)

    def _search_chunks_sync(
        self,
        knowledge_base_id: int,
        query_text: str,
        query_embedding: list[float],
        search_mode: str,
        final_top_k: int,
        recall_top_k: int,
        similarity_threshold: float,
        bm25_top_k: int,
        vector_weight: float,
        bm25_weight: float,
        bm25_drop_ratio_search: float,
        include_distances: bool,
        document_ids: list[int] | None,
    ) -> list[dict[str, Any]]:
        """执行单个知识库 collection 的召回、过滤和 Top K 截断。"""
        client = self._connect()
        collection_name = self._collection_name(knowledge_base_id)
        if not client.has_collection(collection_name=collection_name):
            return []

        client.load_collection(collection_name=collection_name)
        output_fields = ["chunk_id", "knowledge_base_id", "document_id", "chunk_index", "content"]
        final_top_k = max(1, int(final_top_k))
        recall_top_k = max(final_top_k, int(recall_top_k))
        bm25_top_k = max(1, int(bm25_top_k))
        similarity_threshold = min(max(float(similarity_threshold), 0.0), 1.0)
        bm25_drop_ratio_search = min(max(float(bm25_drop_ratio_search), 0.0), 1.0)
        normalized_mode = self._normalize_search_mode(search_mode)
        expr = self._build_document_filter(document_ids)

        if normalized_mode == "vector":
            # 向量模式使用查询 embedding 做 COSINE 语义召回。
            results = client.search(
                collection_name=collection_name,
                data=[query_embedding],
                anns_field="embedding",
                search_params={"metric_type": VECTOR_METRIC_TYPE, "params": {"nprobe": 10}},
                limit=recall_top_k,
                filter=expr or "",
                output_fields=output_fields,
            )
            chunks = [
                self._build_chunk_from_hit(
                    hit,
                    score=float(hit.get("distance") or 0.0),
                    include_distances=include_distances,
                )
                for hit in results[0]
                if float(hit.get("distance") or 0.0) >= similarity_threshold
            ]
        elif normalized_mode == "keyword":
            # 关键词模式把原始查询文本交给 Milvus analyzer 和 BM25 Function。
            self._require_sparse_field(collection_name)
            results = client.search(
                collection_name=collection_name,
                data=[query_text],
                anns_field=CONTENT_SPARSE_FIELD,
                search_params={
                    "metric_type": "BM25",
                    "params": {"drop_ratio_search": bm25_drop_ratio_search},
                },
                limit=bm25_top_k,
                filter=expr or "",
                output_fields=output_fields,
            )
            chunks = [
                self._build_chunk_from_hit(
                    hit,
                    score=float(hit.get("distance") or 0.0),
                    include_distances=include_distances,
                    score_field="bm25_score",
                )
                for hit in results[0]
            ]
        elif normalized_mode == "hybrid":
            # 混合模式分别召回向量与 BM25 结果，再按配置权重进行融合排序。
            self._require_sparse_field(collection_name)
            dense_request = AnnSearchRequest(
                data=[query_embedding],
                anns_field="embedding",
                param={"metric_type": VECTOR_METRIC_TYPE, "params": {"nprobe": 10}},
                limit=recall_top_k,
                expr=expr or "",
            )
            bm25_request = AnnSearchRequest(
                data=[query_text],
                anns_field=CONTENT_SPARSE_FIELD,
                param={
                    "metric_type": "BM25",
                    "params": {"drop_ratio_search": bm25_drop_ratio_search},
                },
                limit=bm25_top_k,
                expr=expr or "",
            )
            results = client.hybrid_search(
                collection_name=collection_name,
                reqs=[dense_request, bm25_request],
                ranker=WeightedRanker(float(vector_weight), float(bm25_weight)),
                limit=recall_top_k,
                output_fields=output_fields,
            )
            chunks = [
                self._build_chunk_from_hit(
                    hit,
                    score=float(hit.get("distance") or 0.0),
                    include_distances=include_distances,
                    score_field="hybrid_score",
                )
                for hit in results[0]
                if float(hit.get("distance") or 0.0) >= similarity_threshold
            ]

        logger.info(
            "Milvus query completed: collection=%s mode=%s recalled=%s returned=%s",
            collection_name,
            normalized_mode,
            len(chunks),
            min(len(chunks), final_top_k),
        )
        return chunks[:final_top_k]

    def _delete_document_chunks_from_collection(self, collection_name: str, document_id: int) -> None:
        """从指定 collection 删除文档 chunk。"""
        client = self._connect()
        client.load_collection(collection_name=collection_name)
        client.delete(
            collection_name=collection_name,
            filter=f"document_id == {int(document_id)}",
        )
        logger.info(
            "Milvus document chunks deleted: collection=%s document_id=%s",
            collection_name,
            document_id,
        )

    def _get_or_create_collection(self, knowledge_base_id: int, dimension: int) -> str:
        """获取知识库 collection；不存在时创建字段、BM25 Function 和双索引。"""
        client = self._connect()
        collection_name = self._collection_name(knowledge_base_id)
        if client.has_collection(collection_name=collection_name):
            self._ensure_dimension(collection_name, dimension)
            return collection_name

        # content_sparse 由 BM25 Function 自动维护，embedding 由应用侧 embedding 服务生成。
        schema = MilvusClient.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
            description=f"miniBOT knowledge base {knowledge_base_id} vectors",
        )
        schema.add_field(field_name="id", datatype=DataType.VARCHAR, max_length=255, is_primary=True)
        schema.add_field(field_name="chunk_id", datatype=DataType.VARCHAR, max_length=255)
        schema.add_field(field_name="knowledge_base_id", datatype=DataType.INT64)
        schema.add_field(field_name="document_id", datatype=DataType.INT64)
        schema.add_field(field_name="chunk_index", datatype=DataType.INT64)
        schema.add_field(
            field_name="content",
            datatype=DataType.VARCHAR,
            max_length=65535,
            enable_analyzer=True,
            analyzer_params=CONTENT_ANALYZER_PARAMS,
        )
        schema.add_field(field_name="embedding", datatype=DataType.FLOAT_VECTOR, dim=dimension)
        schema.add_field(field_name=CONTENT_SPARSE_FIELD, datatype=DataType.SPARSE_FLOAT_VECTOR)
        bm25_function = Function(
            name="content_bm25",
            function_type=FunctionType.BM25,
            input_field_names=["content"],
            output_field_names=[CONTENT_SPARSE_FIELD],
        )
        schema.add_function(bm25_function)

        index_params = MilvusClient.prepare_index_params()
        index_params.add_index(
            field_name="embedding",
            index_type="IVF_FLAT",
            metric_type=VECTOR_METRIC_TYPE,
            params={"nlist": 1024},
        )
        index_params.add_index(
            field_name=CONTENT_SPARSE_FIELD,
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
            params={"inverted_index_algo": "DAAT_MAXSCORE"},
        )
        client.create_collection(
            collection_name=collection_name,
            schema=schema,
            index_params=index_params,
        )
        client.load_collection(collection_name=collection_name)
        logger.info(
            "Milvus collection created: collection=%s dimension=%s",
            collection_name,
            dimension,
        )
        return collection_name

    def _connect(self) -> MilvusClient:
        """按需创建 MilvusClient，并切换到项目配置的数据库。"""
        if self._client is not None:
            return self._client

        client = MilvusClient(uri=self.uri, token=self.token)
        try:
            databases = client.list_databases()
            if self.database not in databases:
                client.create_database(db_name=self.database)
            client.use_database(db_name=self.database)
        except Exception as error:
            logger.warning("Milvus database selection failed, using default database: %s", error)
        self._client = client
        return client

    def _collection_name(self, knowledge_base_id: int) -> str:
        """根据知识库 ID 生成稳定的 Milvus collection 名称。"""
        return f"{self.collection_prefix}{knowledge_base_id}"

    def _ensure_dimension(self, collection_name: str, dimension: int) -> None:
        """校验已有 collection 的向量维度，避免写入不兼容 embedding。"""
        description = self._connect().describe_collection(collection_name=collection_name)
        for field in description.get("fields", []):
            if field.get("name") == "embedding":
                existing = int((field.get("params") or {}).get("dim") or 0)
                if existing != int(dimension):
                    raise ValueError(
                        f"Milvus collection {collection_name} dimension mismatch: "
                        f"existing={existing}, requested={dimension}."
                    )
                return

    def _require_sparse_field(self, collection_name: str) -> None:
        """确认 collection 已使用包含 BM25 稀疏字段的新 schema。"""
        description = self._connect().describe_collection(collection_name=collection_name)
        fields = description.get("fields", [])
        if not any(field.get("name") == CONTENT_SPARSE_FIELD for field in fields):
            raise ValueError(f"Milvus collection {collection_name} does not contain BM25 fields.")

    def _build_chunk_from_hit(
        self,
        hit: Any,
        *,
        score: float,
        include_distances: bool,
        score_field: str | None = None,
    ) -> dict[str, Any]:
        """把 Milvus 命中记录转换为统一的 content、metadata、score 结构。"""
        entity = hit.get("entity") or {}
        distance = float(hit.get("distance") or 0.0)
        chunk = {
            "content": entity.get("content") or "",
            "metadata": {
                "chunk_id": entity.get("chunk_id"),
                "knowledge_base_id": entity.get("knowledge_base_id"),
                "document_id": entity.get("document_id"),
                "chunk_index": entity.get("chunk_index"),
            },
            "score": float(score),
            "retrieval_source": "milvus",
        }
        if score_field:
            chunk[score_field] = float(score)
        if include_distances:
            chunk["distance"] = distance
        return chunk

    def _normalize_search_mode(self, search_mode: str) -> str:
        """规范检索模式，并兼容旧的 dense、bm25 配置名称。"""
        aliases = {"dense": "vector", "bm25": "keyword"}
        normalized = aliases.get(str(search_mode).lower(), str(search_mode).lower())
        if normalized not in {"vector", "keyword", "hybrid"}:
            return "vector"
        return normalized

    def _build_document_filter(self, document_ids: list[int] | None) -> str | None:
        """根据文档 ID 构造 Milvus 标量过滤表达式。"""
        if document_ids is None:
            return None
        normalized_ids = sorted({int(document_id) for document_id in document_ids})
        if not normalized_ids:
            return "document_id == -1"
        if len(normalized_ids) == 1:
            return f"document_id == {normalized_ids[0]}"
        return f"document_id in {normalized_ids}"
