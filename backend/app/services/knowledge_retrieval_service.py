import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import KnowledgeBaseRepository, KnowledgeDocumentRepository
from app.embedding import get_embedding_service
from app.vectorstores import get_vector_store

logger = logging.getLogger(__name__)


class KnowledgeRetrievalService:
    def __init__(self, db: AsyncSession):
        self.base_repo = KnowledgeBaseRepository(db)
        self.document_repo = KnowledgeDocumentRepository(db)
        self.embedding_service = get_embedding_service()
        self.vector_store = get_vector_store()

    async def query(
        self,
        *,
        user_key: str,
        query: str,
        knowledge_base_ids: list[int] | None = None,
        search_mode: str = "hybrid",
        final_top_k: int = 5,
        similarity_threshold: float = 0.0,
        bm25_top_k: int = 50,
        vector_weight: float = 0.7,
        bm25_weight: float = 0.3,
        bm25_drop_ratio_search: float = 0.0,
        include_distances: bool = True,
        recall_top_k: int = 50,
        file_name: str | None = None,
    ) -> dict[str, Any]:
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("Knowledge query cannot be empty.")

        normalized_mode = self._normalize_search_mode(search_mode)
        final_top_k = min(max(int(final_top_k), 1), 100)
        recall_top_k = min(max(int(recall_top_k), final_top_k), 200)
        bm25_top_k = min(max(int(bm25_top_k), 1), 200)
        vector_weight, bm25_weight = self._normalize_weights(vector_weight, bm25_weight)
        bases = await self._resolve_bases(user_key, knowledge_base_ids)
        if not bases:
            return {
                "query": clean_query,
                "search_mode": normalized_mode,
                "results": [],
                "searched_knowledge_base_ids": [],
            }

        query_embedding = (await self.embedding_service.embed_texts([clean_query]))[0]
        searches = [
            self._search_base(
                knowledge_base_id=base.id,
                query=clean_query,
                query_embedding=query_embedding,
                search_mode=normalized_mode,
                recall_top_k=recall_top_k,
                similarity_threshold=similarity_threshold,
                bm25_top_k=bm25_top_k,
                vector_weight=vector_weight,
                bm25_weight=bm25_weight,
                bm25_drop_ratio_search=bm25_drop_ratio_search,
                include_distances=include_distances,
                document_ids=await self._resolve_document_ids(base.id, file_name),
            )
            for base in bases
        ]
        grouped_results = await asyncio.gather(*searches)
        results = [item for group in grouped_results for item in group]
        results.sort(key=lambda item: item["score"], reverse=True)
        results = results[:final_top_k]
        await self._attach_document_metadata(results)

        return {
            "query": clean_query,
            "search_mode": normalized_mode,
            "results": results,
            "searched_knowledge_base_ids": [base.id for base in bases],
        }

    async def _resolve_bases(self, user_key: str, requested_ids: list[int] | None) -> list[Any]:
        bases = await self.base_repo.list(user_key)
        if not requested_ids:
            return bases
        allowed_ids = {int(item) for item in requested_ids}
        return [base for base in bases if base.id in allowed_ids]

    async def _search_base(
        self,
        *,
        knowledge_base_id: int,
        query: str,
        query_embedding: list[float],
        search_mode: str,
        recall_top_k: int,
        similarity_threshold: float,
        bm25_top_k: int,
        vector_weight: float,
        bm25_weight: float,
        bm25_drop_ratio_search: float,
        include_distances: bool,
        document_ids: list[int] | None,
    ) -> list[dict[str, Any]]:
        try:
            # LightRAG or other retrievers can be added beside this Milvus call,
            # then fused here without changing the tool-facing result contract.
            return await self.vector_store.search_chunks(
                knowledge_base_id=knowledge_base_id,
                query_text=query,
                query_embedding=query_embedding,
                search_mode=search_mode,
                final_top_k=recall_top_k,
                recall_top_k=recall_top_k,
                similarity_threshold=similarity_threshold,
                bm25_top_k=bm25_top_k,
                vector_weight=vector_weight,
                bm25_weight=bm25_weight,
                bm25_drop_ratio_search=bm25_drop_ratio_search,
                include_distances=include_distances,
                document_ids=document_ids,
            )
        except ValueError as error:
            # Old collections may not contain sparse fields; they are ignored until reindexed.
            logger.warning(
                "Knowledge collection skipped: knowledge_base_id=%s mode=%s error=%s",
                knowledge_base_id,
                search_mode,
                error,
            )
            return []

    async def _attach_document_metadata(self, results: list[dict[str, Any]]) -> None:
        document_ids = sorted({int(item["metadata"]["document_id"]) for item in results})
        documents = await self.document_repo.get_by_ids(document_ids)
        documents_by_id = {document.id: document for document in documents}
        for item in results:
            metadata = item["metadata"]
            document = documents_by_id.get(int(metadata["document_id"]))
            metadata["source"] = document.filename if document else ""
            metadata["citation_id"] = (
                f"kb:{metadata['knowledge_base_id']}:doc:{metadata['document_id']}:chunk:{metadata['chunk_id']}"
            )

    async def _resolve_document_ids(self, knowledge_base_id: int, file_name: str | None) -> list[int] | None:
        if not file_name:
            return None
        pattern = file_name.replace("%", "").strip().lower()
        documents = await self.document_repo.list(knowledge_base_id)
        return [document.id for document in documents if pattern in document.filename.lower()]

    def _normalize_search_mode(self, search_mode: str) -> str:
        aliases = {"dense": "vector", "bm25": "keyword"}
        normalized = aliases.get(str(search_mode).lower(), str(search_mode).lower())
        if normalized not in {"vector", "keyword", "hybrid"}:
            return "vector"
        return normalized

    def _normalize_weights(self, vector_weight: float, bm25_weight: float) -> tuple[float, float]:
        vector_weight = max(float(vector_weight), 0.0)
        bm25_weight = max(float(bm25_weight), 0.0)
        if vector_weight == 0.0 and bm25_weight == 0.0:
            return 0.7, 0.3
        return vector_weight, bm25_weight
