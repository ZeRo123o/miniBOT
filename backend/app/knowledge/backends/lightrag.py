import asyncio
import logging
import os
import shutil
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from app.core.config import get_settings
from app.embedding import get_embedding_service
from app.knowledge.backends.base import KnowledgeBackend

logger = logging.getLogger(__name__)


class LightRAGKnowledgeBackend(KnowledgeBackend):
    """使用 LightRAG 管理独立的向量集合、文档状态和 Neo4j 图数据。"""

    backend_type = "lightrag"
    _chunk_delimiter = "\n<|MINIBOT_CHUNK_DELIM|>\n"

    def __init__(self) -> None:
        self.settings = get_settings()
        self.embedding_service = get_embedding_service()
        self._instances: dict[int, Any] = {}
        self._instance_locks: dict[int, asyncio.Lock] = {}
        self._write_locks: dict[int, asyncio.Lock] = {}
        self._lock_guard = asyncio.Lock()

    async def index_document(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        filename: str,
        markdown: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        lock = await self._get_lock(self._write_locks, knowledge_base_id)
        async with lock:
            rag = await self._get_instance(knowledge_base_id)
            payload = self._chunk_delimiter.join(
                str(chunk.get("content") or "").strip()
                for chunk in chunks
                if str(chunk.get("content") or "").strip()
            )
            if not payload:
                payload = markdown

            insert_kwargs = {
                "input": payload,
                "ids": str(document_id),
                # 使用 document_id 作为 LightRAG file_path，便于检索结果映射回业务文档。
                "file_paths": str(document_id),
                "split_by_character": self._chunk_delimiter if len(chunks) > 1 else None,
                "split_by_character_only": False,
            }
            try:
                await rag.ainsert(**insert_kwargs)
            except TypeError:
                # 兼容不支持预分块参数的 LightRAG 小版本。
                await rag.ainsert(input=payload, ids=str(document_id), file_paths=str(document_id))

            await self._ensure_document_processed(rag, str(document_id))
            return {
                "content_store": "lightrag",
                "graph_store": "neo4j",
                "vector_store": "lightrag_milvus",
                "lightrag_workspace": self._workspace(knowledge_base_id),
            }

    async def delete_document(self, *, knowledge_base_id: int, document_id: int) -> None:
        lock = await self._get_lock(self._write_locks, knowledge_base_id)
        async with lock:
            rag = await self._get_instance(knowledge_base_id)
            await rag.adelete_by_doc_id(str(document_id))

    async def delete_knowledge_base(
        self,
        *,
        knowledge_base_id: int,
        document_ids: list[int],
    ) -> None:
        """Delete every LightRAG document, then release and remove its workspace."""
        lock = await self._get_lock(self._write_locks, knowledge_base_id)
        async with lock:
            rag = await self._get_instance(knowledge_base_id) if document_ids else self._instances.get(knowledge_base_id)
            if rag is not None:
                for document_id in document_ids:
                    await rag.adelete_by_doc_id(str(document_id), delete_llm_cache=True)
                await rag.finalize_storages()

            self._instances.pop(knowledge_base_id, None)
            self._instance_locks.pop(knowledge_base_id, None)
            working_dir = Path(self.settings.lightrag_work_dir) / self._workspace(knowledge_base_id)
            if working_dir.exists():
                await asyncio.to_thread(shutil.rmtree, working_dir)

        async with self._lock_guard:
            self._write_locks.pop(knowledge_base_id, None)

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
        _, QueryParam, _, _ = self._load_lightrag()
        rag = await self._get_instance(knowledge_base_id)
        mode = self._normalize_query_mode(
            kwargs.get("lightrag_query_mode") or self.settings.lightrag_query_mode
        )
        param = QueryParam(
            mode=mode,
            only_need_context=True,
            top_k=recall_top_k,
            chunk_top_k=recall_top_k,
            enable_rerank=False,
            include_references=True,
        )

        if hasattr(rag, "aquery_data"):
            response = await rag.aquery_data(query_text, param)
        else:
            response = await rag.aquery(query_text, param)
        return self._normalize_query_results(
            rag=rag,
            response=response,
            knowledge_base_id=knowledge_base_id,
            final_top_k=final_top_k,
            document_ids=document_ids,
        )

    async def _get_instance(self, knowledge_base_id: int) -> Any:
        cached = self._instances.get(knowledge_base_id)
        if cached is not None:
            return cached

        lock = await self._get_lock(self._instance_locks, knowledge_base_id)
        async with lock:
            cached = self._instances.get(knowledge_base_id)
            if cached is not None:
                return cached

            LightRAG, _, EmbeddingFunc, initialize_pipeline_status = self._load_lightrag()
            self._configure_storage_environment()
            await asyncio.to_thread(self._ensure_milvus_database)
            working_dir = Path(self.settings.lightrag_work_dir) / self._workspace(knowledge_base_id)
            working_dir.mkdir(parents=True, exist_ok=True)
            rag = LightRAG(
                working_dir=str(working_dir),
                workspace=self._workspace(knowledge_base_id),
                llm_model_func=self._llm_complete,
                embedding_func=EmbeddingFunc(
                    embedding_dim=self.embedding_service.dimension,
                    max_token_size=self.settings.lightrag_embedding_max_tokens,
                    func=self._embed_texts,
                ),
                vector_storage="MilvusVectorDBStorage",
                kv_storage="JsonKVStorage",
                graph_storage="Neo4JStorage",
                doc_status_storage="JsonDocStatusStorage",
                addon_params={"language": self.settings.lightrag_language},
            )
            await rag.initialize_storages()
            await initialize_pipeline_status()
            self._instances[knowledge_base_id] = rag
            return rag

    async def _llm_complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history_messages: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        provider = (
            self.settings.lightrag_model_provider
            or self.settings.chat_model_provider
            or self.settings.default_model_provider
        ).lower()
        model_name = (
            self.settings.lightrag_model_name
            or self.settings.chat_model_name
            or self.settings.default_model_name
            or self.settings.default_model
        )
        if provider == "mock" or model_name == "mock":
            raise ValueError("LightRAG requires a real OpenAI-compatible LLM configuration.")
        if not self.settings.openai_api_key:
            raise ValueError("MINIBOT_OPENAI_API_KEY is required for LightRAG.")

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.extend(history_messages or [])
        messages.append({"role": "user", "content": prompt})
        payload = {
            "model": model_name,
            "messages": messages,
            "temperature": self.settings.openai_temperature,
        }
        async with httpx.AsyncClient(timeout=self.settings.lightrag_llm_timeout) as client:
            response = await client.post(
                f"{self.settings.openai_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()
        return str(data["choices"][0]["message"].get("content") or "")

    async def _embed_texts(self, texts: list[str]) -> np.ndarray:
        """把项目 Embedding 服务结果转换为 LightRAG 期望的二维数组。"""
        embeddings = await self.embedding_service.embed_texts(texts)
        return np.asarray(embeddings, dtype=np.float32)

    def _normalize_query_results(
        self,
        *,
        rag: Any,
        response: Any,
        knowledge_base_id: int,
        final_top_k: int,
        document_ids: list[int] | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(response, dict):
            if not response:
                return []
            return [
                {
                    "content": str(response),
                    "metadata": {
                        "knowledge_base_id": knowledge_base_id,
                        "retrieval_source": "lightrag",
                        "retrieval_kind": "context",
                    },
                    "score": 1.0,
                }
            ]

        data = response.get("data") or response
        raw_chunks = data.get("chunks") or []
        allowed_document_ids = set(document_ids) if document_ids is not None else None
        normalized = []
        for index, raw_chunk in enumerate(raw_chunks):
            if not isinstance(raw_chunk, dict):
                continue
            metadata = dict(raw_chunk.get("metadata") or {})
            chunk_id = (
                metadata.get("chunk_id")
                or raw_chunk.get("chunk_id")
                or raw_chunk.get("id")
            )
            stored_chunk = self._get_stored_chunk(rag, chunk_id)
            document_id = (
                metadata.get("document_id")
                or metadata.get("file_id")
                or raw_chunk.get("full_doc_id")
                or stored_chunk.get("full_doc_id")
                or raw_chunk.get("file_path")
            )
            try:
                document_id = int(document_id)
            except (TypeError, ValueError):
                document_id = None
            if allowed_document_ids is not None and document_id not in allowed_document_ids:
                continue

            content = raw_chunk.get("content") or stored_chunk.get("content") or ""
            if not str(content).strip():
                continue
            score = raw_chunk.get("score")
            if score is None:
                score = max(0.0, 1.0 - index / max(len(raw_chunks), 1))
            normalized.append(
                {
                    "content": str(content),
                    "metadata": {
                        **metadata,
                        "knowledge_base_id": knowledge_base_id,
                        "document_id": document_id,
                        "chunk_id": str(chunk_id or f"lightrag_{index}"),
                        "retrieval_source": "lightrag",
                        "retrieval_kind": "chunk",
                    },
                    "score": float(score),
                }
            )
        return normalized[:final_top_k]

    @staticmethod
    def _get_stored_chunk(rag: Any, chunk_id: Any) -> dict[str, Any]:
        if not chunk_id:
            return {}
        text_chunks = getattr(rag, "text_chunks", None)
        chunk_store = getattr(text_chunks, "_data", None)
        if not isinstance(chunk_store, dict):
            return {}
        stored = chunk_store.get(chunk_id)
        return stored if isinstance(stored, dict) else {}

    async def _ensure_document_processed(self, rag: Any, document_id: str) -> None:
        doc_status = getattr(rag, "doc_status", None)
        if doc_status is None or not hasattr(doc_status, "get_by_id"):
            return
        status_doc = await doc_status.get_by_id(document_id)
        if not status_doc:
            raise ValueError(f"LightRAG document status is missing: {document_id}")
        status = status_doc.get("status")
        status_value = status.value if hasattr(status, "value") else status
        if status_value not in {"processed", "preprocessed"}:
            error = status_doc.get("error_msg") or "unknown error"
            raise ValueError(
                f"LightRAG indexing failed: document_id={document_id}, "
                f"status={status_value}, error={error}"
            )

    async def _get_lock(
        self,
        lock_map: dict[int, asyncio.Lock],
        knowledge_base_id: int,
    ) -> asyncio.Lock:
        async with self._lock_guard:
            return lock_map.setdefault(knowledge_base_id, asyncio.Lock())

    def _configure_storage_environment(self) -> None:
        os.environ["MILVUS_URI"] = self.settings.lightrag_milvus_uri or self.settings.milvus_uri
        os.environ["MILVUS_TOKEN"] = self.settings.lightrag_milvus_token or self.settings.milvus_token
        os.environ["MILVUS_DB_NAME"] = self.settings.lightrag_milvus_db
        os.environ["NEO4J_URI"] = self.settings.neo4j_uri
        os.environ["NEO4J_USERNAME"] = self.settings.neo4j_username
        os.environ["NEO4J_PASSWORD"] = self.settings.neo4j_password

    def _ensure_milvus_database(self) -> None:
        """在 LightRAG 初始化 storage 前确保独立 Milvus database 已存在。"""
        from pymilvus import MilvusClient

        client = MilvusClient(
            uri=self.settings.lightrag_milvus_uri or self.settings.milvus_uri,
            token=self.settings.lightrag_milvus_token or self.settings.milvus_token,
        )
        databases = client.list_databases()
        if self.settings.lightrag_milvus_db not in databases:
            client.create_database(db_name=self.settings.lightrag_milvus_db)

    @staticmethod
    def _load_lightrag() -> tuple[Any, Any, Any, Any]:
        try:
            from lightrag import LightRAG, QueryParam
            from lightrag.kg.shared_storage import initialize_pipeline_status
            from lightrag.utils import EmbeddingFunc
        except ImportError as error:
            raise RuntimeError(
                "LightRAG backend is not installed. Run pip install -r backend/requirements.txt."
            ) from error
        return LightRAG, QueryParam, EmbeddingFunc, initialize_pipeline_status

    def _workspace(self, knowledge_base_id: int) -> str:
        return f"{self.settings.lightrag_workspace_prefix}{knowledge_base_id}"

    @staticmethod
    def _normalize_query_mode(mode: Any) -> str:
        normalized = str(mode or get_settings().lightrag_query_mode or "mix").lower()
        if normalized in {"local", "global", "hybrid", "naive", "mix"}:
            return normalized
        return "mix"
