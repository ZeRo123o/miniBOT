from typing import Any

from app.knowledge.backends.base import KnowledgeBackend
from app.knowledge.embedding import get_embedding_service
from app.vectorstores import get_vector_store


class MilvusKnowledgeBackend(KnowledgeBackend):
    """沿用 miniBOT 原有的分块、Embedding 和 Milvus 混合检索链路。"""

    backend_type = "milvus"

    def __init__(self) -> None:
        self.vector_store = get_vector_store()

    async def index_document(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        filename: str,
        markdown: str,
        chunks: list[dict[str, Any]],
        knowledge_base_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        embedding_service = get_embedding_service((knowledge_base_metadata or {}).get("embedding_model_spec"))
        texts = [chunk["content"] for chunk in chunks]
        embeddings = await embedding_service.embed_texts(texts)
        await self.vector_store.upsert_chunks(
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
            chunks=chunks,
            embeddings=embeddings,
            dimension=embedding_service.dimension,
        )
        return {
            "content_store": "milvus",
            "embedding_count": len(embeddings),
            "embedding_model": embedding_service.model_name,
            "embedding_model_spec": (knowledge_base_metadata or {}).get("embedding_model_spec"),
            "vector_store": "milvus",
        }

    async def delete_document(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        knowledge_base_metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.vector_store.delete_document_chunks(
            knowledge_base_id=knowledge_base_id,
            document_id=document_id,
        )

    async def delete_knowledge_base(
        self,
        *,
        knowledge_base_id: int,
        document_ids: list[int],
        knowledge_base_metadata: dict[str, Any] | None = None,
    ) -> None:
        await self.vector_store.delete_knowledge_base(knowledge_base_id=knowledge_base_id)

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
        embedding_service = get_embedding_service(kwargs.get("embedding_model_spec"))
        query_embedding = (await embedding_service.embed_texts([query_text]))[0]
        return await self.vector_store.search_chunks(
            knowledge_base_id=knowledge_base_id,
            query_text=query_text,
            query_embedding=query_embedding,
            search_mode=kwargs.get("search_mode", "hybrid"),
            final_top_k=final_top_k,
            recall_top_k=recall_top_k,
            similarity_threshold=kwargs.get("similarity_threshold", 0.0),
            bm25_top_k=kwargs.get("bm25_top_k", 50),
            vector_weight=kwargs.get("vector_weight", 0.7),
            bm25_weight=kwargs.get("bm25_weight", 0.3),
            bm25_drop_ratio_search=kwargs.get("bm25_drop_ratio_search", 0.0),
            include_distances=kwargs.get("include_distances", True),
            document_ids=document_ids,
        )
