import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.repositories import KnowledgeBaseRepository, KnowledgeDocumentRepository
from app.knowledge.backends import get_knowledge_backend, normalize_knowledge_backend_type
from app.knowledge.rerank import get_rerank_service

logger = logging.getLogger(__name__)

DEFAULT_QUERY_PARAMS = {
    "search_mode": "hybrid",
    "final_top_k": 10,
    "similarity_threshold": 0.0,
    "bm25_top_k": 50,
    "vector_weight": 0.7,
    "bm25_weight": 0.3,
    "bm25_drop_ratio_search": 0.0,
    "include_distances": True,
    "recall_top_k": 50,
    "use_reranker": None,
    "reranker_model": None,
}


class KnowledgeRetrievalService:
    def __init__(self, db: AsyncSession):
        self.base_repo = KnowledgeBaseRepository(db)
        self.document_repo = KnowledgeDocumentRepository(db)

    async def query(
        self,
        *,
        user_id: str,
        query: str,
        knowledge_base_ids: list[int] | None = None,
        search_mode: str | None = None,
        final_top_k: int | None = None,
        similarity_threshold: float | None = None,
        bm25_top_k: int | None = None,
        vector_weight: float | None = None,
        bm25_weight: float | None = None,
        bm25_drop_ratio_search: float | None = None,
        include_distances: bool | None = None,
        recall_top_k: int | None = None,
        file_name: str | None = None,
        use_reranker: bool | None = None,
        reranker_model: str | None = None,
    ) -> dict[str, Any]:
        clean_query = query.strip()
        if not clean_query:
            raise ValueError("Knowledge query cannot be empty.")

        bases = await self._resolve_bases(user_id, knowledge_base_ids)
        query_params = self._resolve_query_params(
            bases=bases,
            explicit={
                "search_mode": search_mode,
                "final_top_k": final_top_k,
                "similarity_threshold": similarity_threshold,
                "bm25_top_k": bm25_top_k,
                "vector_weight": vector_weight,
                "bm25_weight": bm25_weight,
                "bm25_drop_ratio_search": bm25_drop_ratio_search,
                "include_distances": include_distances,
                "recall_top_k": recall_top_k,
                "use_reranker": use_reranker,
                "reranker_model": reranker_model,
            },
        )
        settings = get_settings()
        should_rerank = settings.rerank_enabled if query_params["use_reranker"] is None else bool(query_params["use_reranker"])
        normalized_mode = self._normalize_search_mode(query_params["search_mode"])
        final_top_k = min(max(int(query_params["final_top_k"]), 1), 100)
        recall_top_k = min(max(int(query_params["recall_top_k"]), final_top_k), 200)
        if should_rerank:
            recall_top_k = min(max(recall_top_k, final_top_k, 50), 200)
        bm25_top_k = min(max(int(query_params["bm25_top_k"]), 1), 200)
        vector_weight, bm25_weight = self._normalize_weights(query_params["vector_weight"], query_params["bm25_weight"])
        similarity_threshold = float(query_params["similarity_threshold"])
        bm25_drop_ratio_search = float(query_params["bm25_drop_ratio_search"])
        include_distances = bool(query_params["include_distances"])
        reranker_model = query_params["reranker_model"]
        if not bases:
            return {
                "query": clean_query,
                "search_mode": normalized_mode,
                "results": [],
                "searched_knowledge_base_ids": [],
            }

        searches = [
            self._search_base(
                knowledge_base=base,
                query=clean_query,
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
        if should_rerank:
            results = await self._rerank_results(
                query=clean_query,
                results=results,
                reranker_model=reranker_model,
            )
        results = results[:final_top_k]
        await self._attach_document_metadata(results)

        return {
            "query": clean_query,
            "search_mode": normalized_mode,
            "results": results,
            "searched_knowledge_base_ids": [base.id for base in bases],
        }

    async def _resolve_bases(self, user_id: str, requested_ids: list[int] | None) -> list[Any]:
        bases = await self.base_repo.list(user_id)
        if not requested_ids:
            return bases
        allowed_ids = {int(item) for item in requested_ids}
        return [base for base in bases if base.id in allowed_ids]

    def _resolve_query_params(self, *, bases: list[Any], explicit: dict[str, Any]) -> dict[str, Any]:
        params = dict(DEFAULT_QUERY_PARAMS)
        if bases:
            params.update(self._saved_query_options(bases[0]))
        params.update({key: value for key, value in explicit.items() if value is not None})
        return params

    def _saved_query_options(self, knowledge_base: Any) -> dict[str, Any]:
        metadata = knowledge_base.metadata_ or {}
        query_params = metadata.get("query_params") or {}
        options = query_params.get("options") if isinstance(query_params, dict) else {}
        if isinstance(options, dict):
            return dict(options)
        legacy_options = metadata.get("query_config")
        return dict(legacy_options) if isinstance(legacy_options, dict) else {}

    async def _search_base(
        self,
        *,
        knowledge_base: Any,
        query: str,
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
        knowledge_base_id = int(knowledge_base.id)
        metadata = knowledge_base.metadata_ or {}
        kb_type = normalize_knowledge_backend_type(metadata.get("kb_type"))
        backend = get_knowledge_backend(kb_type)
        try:
            return await backend.query(
                knowledge_base_id=knowledge_base_id,
                query_text=query,
                final_top_k=recall_top_k,
                recall_top_k=recall_top_k,
                search_mode=search_mode,
                similarity_threshold=similarity_threshold,
                bm25_top_k=bm25_top_k,
                vector_weight=vector_weight,
                bm25_weight=bm25_weight,
                bm25_drop_ratio_search=bm25_drop_ratio_search,
                include_distances=include_distances,
                document_ids=document_ids,
                embedding_model_spec=metadata.get("embedding_model_spec"),
                lightrag_query_mode=metadata.get("lightrag_query_mode") or None,
            )
        except ValueError as error:
            if kb_type == "lightrag":
                raise
            logger.warning(
                "Knowledge backend skipped: knowledge_base_id=%s kb_type=%s mode=%s error=%s",
                knowledge_base_id,
                kb_type,
                search_mode,
                error,
            )
            return []

    async def _rerank_results(
        self,
        *,
        query: str,
        results: list[dict[str, Any]],
        reranker_model: str | None,
    ) -> list[dict[str, Any]]:
        if not results:
            return results
        documents = [str(item.get("content") or "") for item in results]
        if not any(document.strip() for document in documents):
            return results

        try:
            reranker = get_rerank_service(model_name=reranker_model)
            scores = await reranker.rerank(query=query, documents=documents)
            if len(scores) != len(results):
                raise ValueError(f"Rerank returned {len(scores)} scores for {len(results)} results.")
        except Exception as error:
            logger.warning("Knowledge rerank failed; falling back to original retrieval order: %s", error)
            return results

        for item, score in zip(results, scores, strict=True):
            item["rerank_score"] = float(score)
        results.sort(key=lambda item: item.get("rerank_score", item.get("score", 0.0)), reverse=True)
        logger.info(
            "Knowledge rerank completed: model=%s candidates=%s",
            reranker_model or "default",
            len(results),
        )
        return results

    async def _attach_document_metadata(self, results: list[dict[str, Any]]) -> None:
        document_ids = sorted(
            {
                int(item["metadata"]["document_id"])
                for item in results
                if item.get("metadata", {}).get("document_id") is not None
            }
        )
        documents = await self.document_repo.get_by_ids(document_ids)
        documents_by_id = {document.id: document for document in documents}
        for item in results:
            metadata = item["metadata"]
            document_id = metadata.get("document_id")
            document = documents_by_id.get(int(document_id)) if document_id is not None else None
            metadata["source"] = document.filename if document else ""
            if document is not None:
                metadata["citation_id"] = (
                    f"kb:{metadata['knowledge_base_id']}:doc:{document.id}:chunk:{metadata['chunk_id']}"
                )

    async def _resolve_document_ids(self, knowledge_base_id: int, file_name: str | None) -> list[int] | None:
        documents = await self.document_repo.list(knowledge_base_id)
        indexed_documents = [document for document in documents if document.status == "indexed"]
        if not file_name:
            return [document.id for document in indexed_documents]

        pattern = file_name.replace("%", "").strip().lower()
        return [
            document.id
            for document in indexed_documents
            if pattern in document.filename.lower()
        ]

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
