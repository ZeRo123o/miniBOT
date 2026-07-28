from __future__ import annotations

import asyncio
import logging
import weakref
from dataclasses import MISSING, dataclass, field, fields
from typing import Any

from pymilvus import (
    AnnSearchRequest,
    DataType,
    Function,
    FunctionType,
    MilvusClient,
    WeightedRanker,
)

from app.core.config import get_settings
from app.knowledge.backends.base import KnowledgeBackend
from app.knowledge.embedding import get_embedding_service
from app.llm.providers.cache import model_cache

logger = logging.getLogger(__name__)

CONTENT_SPARSE_FIELD = "content_sparse"
CONTENT_ANALYZER_PARAMS = {"type": "chinese"}
VECTOR_METRIC_TYPE = "COSINE"
MILVUS_CHUNK_EMBED_BATCH_SIZE = 200
_milvus_semaphores: dict[
    int,
    tuple[weakref.ReferenceType[asyncio.AbstractEventLoop], weakref.ReferenceType[asyncio.Semaphore]],
] = {}


def _get_milvus_query_offload_semaphore() -> asyncio.Semaphore:
    """每个事件循环独享限流器，避免阻塞 SDK 占满默认线程池。"""
    loop = asyncio.get_running_loop()
    loop_id = id(loop)
    entry = _milvus_semaphores.get(loop_id)
    if entry and entry[0]() is loop and (semaphore := entry[1]()) is not None:
        return semaphore

    semaphore = asyncio.Semaphore(max(1, get_settings().milvus_query_offload_limit))

    def cleanup(ref: weakref.ReferenceType[asyncio.Semaphore], stale_loop_id: int = loop_id) -> None:
        current = _milvus_semaphores.get(stale_loop_id)
        if current is not None and current[1] is ref:
            _milvus_semaphores.pop(stale_loop_id, None)

    _milvus_semaphores[loop_id] = (
        weakref.ref(loop),
        weakref.ref(semaphore, cleanup),
    )
    return semaphore


async def run_milvus_io(func: Any, /, *args: Any, **kwargs: Any) -> Any:
    """在线程中执行同步 Milvus 调用，并让取消操作只停止等待、不误放并发容量。"""
    semaphore = _get_milvus_query_offload_semaphore()
    await semaphore.acquire()
    task = asyncio.create_task(asyncio.to_thread(func, *args, **kwargs))

    def release_capacity(completed: asyncio.Task) -> None:
        semaphore.release()
        if not completed.cancelled():
            completed.exception()

    task.add_done_callback(release_capacity)
    return await asyncio.shield(task)


@dataclass(kw_only=True)
class MilvusRetrievalConfig:
    """Milvus 主索引、图增强和重排的统一查询配置。"""

    search_mode: str = field(
        default="vector",
        metadata={
            "label": "检索模式",
            "type": "select",
            "options": [
                {"value": "vector", "label": "向量检索", "description": "仅使用向量相似度检索"},
                {"value": "keyword", "label": "BM25 全文检索", "description": "仅使用 Milvus BM25 检索"},
                {"value": "hybrid", "label": "混合检索", "description": "融合向量检索和 BM25 检索"},
            ],
        },
    )
    final_top_k: int = field(
        default=10,
        metadata={"label": "最终返回 Chunk 数", "type": "number", "min": 1, "max": 100},
    )
    similarity_threshold: float = field(
        default=0.0,
        metadata={"label": "相似度阈值", "type": "number", "min": 0.0, "max": 1.0, "step": 0.1},
    )
    bm25_top_k: int = field(
        default=50,
        metadata={"label": "BM25 召回数量", "type": "number", "min": 1, "max": 200},
    )
    vector_weight: float = field(
        default=0.7,
        metadata={"label": "向量检索权重", "type": "number", "min": 0.0, "max": 1.0, "step": 0.1},
    )
    bm25_weight: float = field(
        default=0.3,
        metadata={"label": "BM25 权重", "type": "number", "min": 0.0, "max": 1.0, "step": 0.1},
    )
    bm25_drop_ratio_search: float = field(
        default=0.0,
        metadata={"label": "BM25 稀疏项丢弃比例", "type": "number", "min": 0.0, "max": 1.0, "step": 0.1},
    )
    include_distances: bool = field(
        default=True,
        metadata={"label": "显示相似度", "type": "boolean"},
    )
    use_graph_retrieval: bool = field(
        default=False,
        metadata={"label": "启用图检索", "type": "boolean"},
    )
    graph_entity_top_k: int = field(
        default=10,
        metadata={
            "label": "图实体召回数量",
            "type": "number",
            "min": 1,
            "max": 100,
            "depend_on": ("use_graph_retrieval", True),
        },
    )
    graph_triple_top_k: int = field(
        default=10,
        metadata={
            "label": "图三元组召回数量",
            "type": "number",
            "min": 1,
            "max": 100,
            "depend_on": ("use_graph_retrieval", True),
        },
    )
    graph_max_nodes: int = field(
        default=10000,
        metadata={
            "label": "图检索最大节点数",
            "type": "number",
            "min": 1,
            "max": 50000,
            "depend_on": ("use_graph_retrieval", True),
        },
    )
    graph_top_k: int = field(
        default=20,
        metadata={
            "label": "图召回 Chunk 数",
            "type": "number",
            "min": 1,
            "max": 200,
            "depend_on": ("use_graph_retrieval", True),
        },
    )
    graph_weight: float = field(
        default=1.0,
        metadata={
            "label": "图检索融合权重",
            "type": "number",
            "min": 0.0,
            "max": 5.0,
            "step": 0.1,
            "depend_on": ("use_graph_retrieval", True),
        },
    )
    ppr_damping: float = field(
        default=0.85,
        metadata={
            "label": "PPR 阻尼系数",
            "type": "number",
            "min": 0.1,
            "max": 0.99,
            "step": 0.01,
            "depend_on": ("use_graph_retrieval", True),
        },
    )
    use_reranker: bool = field(
        default=False,
        metadata={"label": "启用重排序", "type": "boolean"},
    )
    reranker_model: str | None = field(
        default=None,
        metadata={
            "label": "重排序模型",
            "type": "select",
            "depend_on": ("use_reranker", True),
            "options_provider": "rerank_models",
        },
    )
    recall_top_k: int = field(
        default=50,
        metadata={
            "label": "召回数量",
            "type": "number",
            "min": 10,
            "max": 200,
            "depend_on": ("use_reranker", True),
        },
    )


def get_default_query_params() -> dict[str, Any]:
    """从配置模型生成默认值，避免 API、服务和 backend 各维护一份常量。"""
    return {
        config_field.name: config_field.default
        for config_field in fields(MilvusRetrievalConfig)
        if config_field.default is not MISSING
    }


def get_query_params_config() -> dict[str, Any]:
    """返回前端可直接渲染的查询参数描述。"""
    options: list[dict[str, Any]] = []
    for config_field in fields(MilvusRetrievalConfig):
        metadata = dict(config_field.metadata)
        options_provider = metadata.pop("options_provider", None)
        option = {
            "key": config_field.name,
            "default": None if config_field.default is MISSING else config_field.default,
            **metadata,
        }
        if options_provider == "rerank_models":
            option["options"] = [
                {"label": info.display_name, "value": info.spec}
                for info in model_cache.get_all_specs("rerank")
            ]
        options.append(option)
    return {"type": "milvus", "options": options}


class MilvusKnowledgeBackend(KnowledgeBackend):
    """Milvus 主索引实现，统一管理集合、入库、检索和图增强。"""

    def __init__(
        self,
        *,
        uri: str | None = None,
        token: str | None = None,
        database: str | None = None,
        collection_prefix: str | None = None,
    ):
        settings = get_settings()
        self.uri = uri or settings.milvus_uri
        self.token = settings.milvus_token if token is None else token
        self.database = database or settings.milvus_db
        self.collection_prefix = collection_prefix or settings.milvus_collection_prefix
        self._client: MilvusClient | None = None

    async def index_document(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        chunks: list[dict[str, Any]],
        knowledge_base_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """索引全部单层 Chunk；PostgreSQL 继续作为正文和状态的权威数据源。"""
        metadata = knowledge_base_metadata or {}
        embedding_service = get_embedding_service(metadata.get("embedding_model_spec"))
        index_chunks = chunks

        if index_chunks:
            # 覆盖写入前只删除一次，随后按批次嵌入和插入，避免大文档占用过多内存。
            await self.delete_document_chunks(
                knowledge_base_id=knowledge_base_id,
                document_id=document_id,
            )
            for start in range(0, len(index_chunks), MILVUS_CHUNK_EMBED_BATCH_SIZE):
                batch = index_chunks[start : start + MILVUS_CHUNK_EMBED_BATCH_SIZE]
                embeddings = await embedding_service.embed_texts(
                    [str(chunk["content"]) for chunk in batch]
                )
                await run_milvus_io(
                    self._insert_chunks_sync,
                    knowledge_base_id,
                    document_id,
                    batch,
                    embeddings,
                    embedding_service.dimension,
                    embedding_service.model_name,
                )

        return {
            "content_store": "milvus",
            "embedding_count": len(index_chunks),
            "embedding_model": embedding_service.model_name,
            "embedding_model_spec": metadata.get("embedding_model_spec"),
            "vector_store": "milvus",
        }

    async def delete_document_chunks(self, *, knowledge_base_id: int, document_id: int) -> None:
        """异步删除指定文档在 Milvus 中保存的全部 chunk。"""
        await run_milvus_io(self._delete_document_chunks_sync, knowledge_base_id, document_id)

    async def delete_document(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
    ) -> None:
        await self.delete_document_chunks(
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )

    async def delete_knowledge_base(
        self,
        *,
        knowledge_base_id: int,
    ) -> None:
        await run_milvus_io(self._delete_knowledge_base_sync, knowledge_base_id)

    async def query(
        self,
        *,
        knowledge_base_id: int,
        query_text: str,
        final_top_k: int,
        recall_top_k: int,
        document_ids: list[int] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """对外查询入口；底层故障时返回空结果并记录完整异常。"""
        try:
            return await self._query(
                knowledge_base_id=knowledge_base_id,
                query_text=query_text,
                final_top_k=final_top_k,
                recall_top_k=recall_top_k,
                document_ids=document_ids,
                **kwargs,
            )
        except Exception:
            logger.exception(
                "Milvus query failed: knowledge_base_id=%s",
                knowledge_base_id,
            )
            return []

    async def _query(
        self,
        *,
        knowledge_base_id: int,
        query_text: str,
        final_top_k: int,
        recall_top_k: int,
        document_ids: list[int] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """执行主召回，再按配置串联图增强与重排序。"""
        config = self._resolve_query_config(
            final_top_k=final_top_k,
            recall_top_k=recall_top_k,
            overrides=kwargs,
        )
        query_embedding: list[float] = []
        if config.search_mode != "keyword":
            embedding_service = get_embedding_service(kwargs.get("embedding_model_spec"))
            query_embedding = (await embedding_service.embed_texts([query_text]))[0]

        recalled = await self._search_chunks(
            knowledge_base_id=knowledge_base_id,
            query_text=query_text,
            query_embedding=query_embedding,
            search_mode=config.search_mode,
            final_top_k=config.recall_top_k,
            recall_top_k=config.recall_top_k,
            similarity_threshold=config.similarity_threshold,
            bm25_top_k=config.bm25_top_k,
            vector_weight=config.vector_weight,
            bm25_weight=config.bm25_weight,
            bm25_drop_ratio_search=config.bm25_drop_ratio_search,
            include_distances=config.include_distances,
            document_ids=document_ids,
        )

        if config.use_graph_retrieval:
            graph_chunks = await self._retrieve_graph_chunks(
                knowledge_base_id=knowledge_base_id,
                query_text=query_text,
                base_chunks=recalled,
                document_ids=document_ids,
                embedding_model_spec=kwargs.get("embedding_model_spec"),
                db_session=kwargs.get("db_session"),
                config=config,
            )
            if graph_chunks:
                recalled = self._fuse_chunk_rankings(
                    recalled,
                    graph_chunks,
                    graph_weight=config.graph_weight,
                )

        if config.use_reranker:
            recalled = await self._rerank_chunks(
                query_text=query_text,
                chunks=recalled,
                reranker_model=config.reranker_model,
            )
        return recalled[: config.final_top_k]

    def get_query_params_config(self, knowledge_base_id: int | None = None) -> dict[str, Any]:
        del knowledge_base_id
        return get_query_params_config()

    async def close(self) -> None:
        """关闭进程内复用的 Milvus 客户端。"""
        client = self._client
        self._client = None
        if client is not None:
            await run_milvus_io(client.close)

    async def _search_chunks(
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
        return await run_milvus_io(
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

    def _resolve_query_config(
        self,
        *,
        final_top_k: int,
        recall_top_k: int,
        overrides: dict[str, Any],
    ) -> MilvusRetrievalConfig:
        defaults = get_default_query_params()
        values = {
            key: overrides.get(key, default)
            for key, default in defaults.items()
        }
        values["final_top_k"] = final_top_k
        values["recall_top_k"] = recall_top_k
        values["search_mode"] = self._normalize_search_mode(values["search_mode"])
        values["final_top_k"] = min(max(int(values["final_top_k"]), 1), 100)
        values["recall_top_k"] = min(
            max(int(values["recall_top_k"]), values["final_top_k"]),
            200,
        )
        values["bm25_top_k"] = min(max(int(values["bm25_top_k"]), 1), 200)
        values["similarity_threshold"] = min(
            max(float(values["similarity_threshold"]), 0.0),
            1.0,
        )
        values["bm25_drop_ratio_search"] = min(
            max(float(values["bm25_drop_ratio_search"]), 0.0),
            1.0,
        )
        values["vector_weight"], values["bm25_weight"] = self._normalize_weights(
            values["vector_weight"],
            values["bm25_weight"],
        )
        if not values["use_reranker"] and not values["use_graph_retrieval"]:
            values["recall_top_k"] = values["final_top_k"]
        return MilvusRetrievalConfig(**values)

    async def _retrieve_graph_chunks(
        self,
        *,
        knowledge_base_id: int,
        query_text: str,
        base_chunks: list[dict[str, Any]],
        document_ids: list[int] | None,
        embedding_model_spec: str | None,
        db_session: Any,
        config: MilvusRetrievalConfig,
    ) -> list[dict[str, Any]]:
        """图增强失败时保留 Milvus 主召回，避免增强链路成为单点故障。"""
        if db_session is None:
            logger.warning(
                "Knowledge graph retrieval skipped: knowledge_base_id=%s database session is missing",
                knowledge_base_id,
            )
            return []

        try:
            # 延迟导入用于避免图向量存储反向复用 Milvus I/O 工具时产生循环依赖。
            from app.knowledge.graphs import MilvusGraphService

            return await MilvusGraphService(db_session).search(
                knowledge_base_id=knowledge_base_id,
                query=query_text,
                base_chunks=base_chunks,
                metadata={"embedding_model_spec": embedding_model_spec},
                entity_top_k=max(int(config.graph_entity_top_k), 1),
                triple_top_k=max(int(config.graph_triple_top_k), 1),
                graph_top_k=max(int(config.graph_top_k), 1),
                graph_max_nodes=max(int(config.graph_max_nodes), 1),
                ppr_damping=min(max(float(config.ppr_damping), 0.1), 0.99),
                document_ids=document_ids,
            )
        except Exception as error:
            logger.warning(
                "Knowledge graph retrieval skipped: knowledge_base_id=%s error=%s",
                knowledge_base_id,
                error,
            )
            return []

    @staticmethod
    def _fuse_chunk_rankings(
        base_chunks: list[dict[str, Any]],
        graph_chunks: list[dict[str, Any]],
        *,
        graph_weight: float,
    ) -> list[dict[str, Any]]:
        """使用 RRF 融合主索引和图召回，避免直接比较异构分数。"""
        fused: dict[str, dict[str, Any]] = {}

        def merge(items: list[dict[str, Any]], source: str, weight: float) -> None:
            for rank, item in enumerate(items, start=1):
                chunk_id = str((item.get("metadata") or {}).get("chunk_id") or "")
                if not chunk_id:
                    continue
                entry = fused.setdefault(
                    chunk_id,
                    {
                        **item,
                        "fusion_score": 0.0,
                        "fusion_sources": [],
                    },
                )
                entry["fusion_score"] += max(weight, 0.0) / (60.0 + rank)
                entry["score"] = entry["fusion_score"]
                if source not in entry["fusion_sources"]:
                    entry["fusion_sources"].append(source)
                if source == "graph":
                    entry["graph_score"] = item.get("graph_score", 0.0)

        merge(base_chunks, "chunk", 1.0)
        merge(graph_chunks, "graph", graph_weight)
        return sorted(
            fused.values(),
            key=lambda item: item.get("fusion_score", 0.0),
            reverse=True,
        )

    async def _rerank_chunks(
        self,
        *,
        query_text: str,
        chunks: list[dict[str, Any]],
        reranker_model: str | None,
    ) -> list[dict[str, Any]]:
        if not chunks:
            return chunks
        if not reranker_model:
            raise ValueError("启用重排序时必须指定 reranker_model。")

        try:
            from app.knowledge.rerank import get_rerank_service

            reranker = get_rerank_service(model_name=reranker_model)
            scores = await reranker.rerank(
                query=query_text,
                documents=[str(chunk.get("content") or "") for chunk in chunks],
            )
            if len(scores) != len(chunks):
                raise ValueError(
                    f"Reranker returned {len(scores)} scores for {len(chunks)} chunks."
                )
            for chunk, score in zip(chunks, scores, strict=True):
                chunk["rerank_score"] = float(score)
            chunks.sort(
                key=lambda item: item.get("rerank_score", item.get("score", 0.0)),
                reverse=True,
            )
        except Exception as error:
            logger.warning("Knowledge rerank failed; using retrieval order: %s", error)
        return chunks

    def _insert_chunks_sync(
        self,
        knowledge_base_id: int,
        document_id: int,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
        dimension: int,
        embedding_model: str,
    ) -> None:
        """向已校验的知识库集合插入一批 chunk。"""
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk count and embedding count do not match.")
        collection_name = self._get_or_create_collection(
            knowledge_base_id,
            dimension,
            embedding_model,
        )

        # 稀疏向量由 Milvus BM25 Function 根据 content 自动生成。
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
        output_fields = [
            "chunk_id",
            "knowledge_base_id",
            "document_id",
            "chunk_index",
            "content",
        ]
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

    def _get_or_create_collection(
        self,
        knowledge_base_id: int,
        dimension: int,
        embedding_model: str,
    ) -> str:
        """获取知识库 collection；不存在时创建字段、BM25 Function 和双索引。"""
        client = self._connect()
        collection_name = self._collection_name(knowledge_base_id)
        if client.has_collection(collection_name=collection_name):
            if self._collection_is_compatible(
                collection_name,
                dimension=dimension,
                embedding_model=embedding_model,
            ):
                return collection_name
            # 本项目不兼容旧 schema 或旧 embedding 模型，直接重建后重新上传数据。
            client.drop_collection(collection_name=collection_name)
            logger.warning(
                "Milvus collection recreated because schema or embedding model changed: collection=%s",
                collection_name,
            )

        # content_sparse 由 BM25 Function 自动维护，embedding 由应用侧 embedding 服务生成。
        schema = MilvusClient.create_schema(
            auto_id=False,
            enable_dynamic_field=False,
            description=(
                f"miniBOT knowledge base {knowledge_base_id}; "
                f"embedding_model={embedding_model}; schema=single_chunk_v1"
            ),
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

    def _collection_is_compatible(
        self,
        collection_name: str,
        *,
        dimension: int,
        embedding_model: str,
    ) -> bool:
        """检查向量维度、模型标记和 BM25 字段是否与当前配置一致。"""
        description = self._connect().describe_collection(collection_name=collection_name)
        collection_description = str(description.get("description") or "")
        if f"embedding_model={embedding_model}" not in collection_description:
            return False
        if "schema=single_chunk_v1" not in collection_description:
            return False
        field_map = {
            str(field.get("name") or ""): field
            for field in description.get("fields", [])
        }
        if CONTENT_SPARSE_FIELD not in field_map:
            return False
        content_field = field_map.get("content") or {}
        content_params = content_field.get("params") or {}
        if content_params.get("enable_analyzer") is not True:
            return False
        for field in description.get("fields", []):
            if field.get("name") == "embedding":
                existing = int((field.get("params") or {}).get("dim") or 0)
                return existing == int(dimension)
        return False

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
        """规范检索模式。"""
        normalized = str(search_mode).lower()
        if normalized not in {"vector", "keyword", "hybrid"}:
            return "vector"
        return normalized

    @staticmethod
    def _normalize_weights(vector_weight: float, bm25_weight: float) -> tuple[float, float]:
        vector = max(float(vector_weight), 0.0)
        keyword = max(float(bm25_weight), 0.0)
        if vector == 0.0 and keyword == 0.0:
            return 0.7, 0.3
        return vector, keyword

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
