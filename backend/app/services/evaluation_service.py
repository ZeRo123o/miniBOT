import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import EvaluationRepository, KnowledgeBaseRepository
from app.knowledge.eval.evaluator import aggregate_metrics, evaluate_question
from app.llm.factory import get_chat_model
from app.services.knowledge_retrieval_service import DEFAULT_QUERY_PARAMS, KnowledgeRetrievalService


def build_evaluation_run_name(started_at: datetime | None = None, hash_value: str | None = None) -> str:
    date_part = (started_at or datetime.utcnow()).strftime("%Y%m%d")
    hash_part = re.sub(r"[^a-fA-F0-9]", "", hash_value or uuid.uuid4().hex).lower()[:6]
    if len(hash_part) < 6:
        hash_part = (hash_part + uuid.uuid4().hex)[:6]
    return f"eval-{date_part}-{hash_part}"


class EvaluationService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.eval_repo = EvaluationRepository(db)
        self.base_repo = KnowledgeBaseRepository(db)

    def _dataset_to_dict(self, row: Any) -> dict[str, Any]:
        return row.to_dict()

    def _dataset_item_to_dict(self, item: Any) -> dict[str, Any]:
        return {
            "item_id": item.item_id,
            "item_index": item.item_index,
            "query": item.query_text,
            "gold_chunk_ids": item.gold_chunk_ids or [],
            "gold_answer": item.gold_answer,
        }

    def _run_item_to_dict(self, item: Any) -> dict[str, Any]:
        return {
            "query": item.query_text,
            "gold_chunk_ids": item.gold_chunk_ids or [],
            "gold_answer": item.gold_answer,
            "generated_answer": item.generated_answer,
            "retrieved_chunks": item.retrieved_chunks or [],
            "metrics": item.metrics or {},
        }

    def _parse_jsonl_questions(self, file_content: bytes) -> tuple[list[dict[str, Any]], bool, bool]:
        questions = []
        has_gold_chunks = False
        has_gold_answers = False
        content = file_content.decode("utf-8-sig")

        for line_number, line in enumerate(content.splitlines(), 1):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"第{line_number}行JSON格式错误: {error}") from error
            query = str(item.get("query") or "").strip()
            if not query:
                raise ValueError(f"第{line_number}行缺少必需的 query 字段")
            gold_chunk_ids = [str(value) for value in item.get("gold_chunk_ids") or [] if str(value).strip()]
            gold_answer = str(item.get("gold_answer") or "").strip() or None
            if gold_chunk_ids:
                has_gold_chunks = True
            if gold_answer:
                has_gold_answers = True
            questions.append(
                {
                    "query": query,
                    "gold_chunk_ids": gold_chunk_ids,
                    "gold_answer": gold_answer,
                }
            )

        if not questions:
            raise ValueError("文件中没有有效的问题数据")
        return questions, has_gold_chunks, has_gold_answers

    def _build_dataset_items(
        self,
        *,
        dataset_id: str,
        knowledge_base_id: int,
        questions: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        return [
            {
                "item_id": f"dataset_item_{uuid.uuid4().hex[:12]}",
                "dataset_id": dataset_id,
                "knowledge_base_id": knowledge_base_id,
                "item_index": index,
                "query_text": item["query"],
                "gold_chunk_ids": item.get("gold_chunk_ids") or [],
                "gold_answer": item.get("gold_answer"),
            }
            for index, item in enumerate(questions)
        ]

    async def _require_base(self, knowledge_base_id: int, user_id: str) -> Any:
        knowledge_base = await self.base_repo.get(knowledge_base_id, user_id)
        if knowledge_base is None:
            raise ValueError("Knowledge base not found")
        return knowledge_base

    async def upload_dataset(
        self,
        *,
        knowledge_base_id: int,
        user_id: str,
        file_content: bytes,
        filename: str,
        name: str,
        description: str = "",
    ) -> dict[str, Any]:
        await self._require_base(knowledge_base_id, user_id)
        questions, has_gold_chunks, has_gold_answers = self._parse_jsonl_questions(file_content)
        dataset_id = f"dataset_{uuid.uuid4().hex[:8]}"
        dataset = await self.eval_repo.create_dataset_with_items(
            {
                "dataset_id": dataset_id,
                "knowledge_base_id": knowledge_base_id,
                "user_id": user_id,
                "name": name.strip() or filename or dataset_id,
                "description": description,
                "item_count": len(questions),
                "has_gold_chunks": has_gold_chunks,
                "has_gold_answers": has_gold_answers,
                "build_metadata": {
                    "source": "upload",
                    "status": "completed",
                    "progress": 100,
                    "filename": filename,
                },
            },
            self._build_dataset_items(
                dataset_id=dataset_id,
                knowledge_base_id=knowledge_base_id,
                questions=questions,
            ),
        )
        return self._dataset_to_dict(dataset)

    async def list_datasets(self, knowledge_base_id: int, user_id: str) -> list[dict[str, Any]]:
        await self._require_base(knowledge_base_id, user_id)
        rows = await self.eval_repo.list_datasets(knowledge_base_id, user_id)
        return [self._dataset_to_dict(row) for row in rows]

    async def get_dataset_detail(
        self,
        *,
        knowledge_base_id: int,
        user_id: str,
        dataset_id: str,
        page: int = 1,
        page_size: int = 10,
    ) -> dict[str, Any]:
        await self._require_base(knowledge_base_id, user_id)
        dataset = await self.eval_repo.get_dataset(dataset_id)
        if dataset is None or dataset.knowledge_base_id != knowledge_base_id or dataset.user_id != user_id:
            raise ValueError("Dataset not found")

        total_items = await self.eval_repo.count_dataset_items(dataset_id)
        items = await self.eval_repo.list_dataset_items(
            dataset_id,
            offset=(page - 1) * page_size,
            limit=page_size,
        )
        data = self._dataset_to_dict(dataset)
        data.update(
            {
                "items": [self._dataset_item_to_dict(item) for item in items],
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total_items": total_items,
                    "total_pages": (total_items + page_size - 1) // page_size,
                },
            }
        )
        return data

    async def delete_dataset(self, *, dataset_id: str, user_id: str) -> None:
        dataset = await self.eval_repo.get_dataset(dataset_id)
        if dataset is None or dataset.user_id != user_id:
            raise ValueError("Dataset not found")
        await self.eval_repo.delete_dataset(dataset)

    def _saved_query_options(self, knowledge_base: Any) -> dict[str, Any]:
        metadata = knowledge_base.metadata_ or {}
        query_params = metadata.get("query_params") or {}
        if isinstance(query_params, dict) and isinstance(query_params.get("options"), dict):
            return dict(query_params["options"])
        return {}

    def _build_retrieval_config(self, knowledge_base: Any, model_config: dict[str, Any] | None) -> dict[str, Any]:
        config = dict(DEFAULT_QUERY_PARAMS)
        config.update(self._saved_query_options(knowledge_base))
        config.update(model_config or {})
        return config

    async def run_evaluation(
        self,
        *,
        knowledge_base_id: int,
        user_id: str,
        dataset_id: str,
        name: str | None = None,
        model_config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        knowledge_base = await self._require_base(knowledge_base_id, user_id)
        dataset = await self.eval_repo.get_dataset(dataset_id)
        if dataset is None or dataset.knowledge_base_id != knowledge_base_id or dataset.user_id != user_id:
            raise ValueError("Dataset not found")

        run_id = f"run_{uuid.uuid4().hex[:8]}"
        run_name = name.strip() if name else build_evaluation_run_name(hash_value=run_id.removeprefix("run_"))
        retrieval_config = self._build_retrieval_config(knowledge_base, model_config)
        run = await self.eval_repo.create_run(
            {
                "run_id": run_id,
                "name": run_name,
                "knowledge_base_id": knowledge_base_id,
                "dataset_id": dataset_id,
                "user_id": user_id,
                "status": "running",
                "retrieval_config": retrieval_config,
                "metrics": {},
                "overall_score": None,
                "total_items": dataset.item_count,
                "completed_items": 0,
                "started_at": datetime.utcnow(),
            }
        )

        try:
            await self._run_evaluation(run, dataset, retrieval_config)
        except Exception as error:
            await self.eval_repo.update_run(
                run,
                {
                    "status": "failed",
                    "error_message": str(error),
                    "completed_at": datetime.utcnow(),
                },
            )
            raise
        return (await self.eval_repo.get_run(run_id)).to_dict()

    async def _run_evaluation(self, run: Any, dataset: Any, retrieval_config: dict[str, Any]) -> None:
        items = await self.eval_repo.list_all_dataset_items(dataset.dataset_id)
        retrieval_service = KnowledgeRetrievalService(self.db)
        answer_llm = get_chat_model() if retrieval_config.get("answer_llm_enabled") else None
        judge_llm = get_chat_model() if retrieval_config.get("judge_llm_enabled") else None
        all_retrieval_metrics = []
        all_answer_metrics = []

        for index, item in enumerate(items):
            query_result = await retrieval_service.query(
                user_id=run.user_id,
                query=item.query_text,
                knowledge_base_ids=[run.knowledge_base_id],
                search_mode=retrieval_config.get("search_mode"),
                final_top_k=retrieval_config.get("final_top_k"),
                recall_top_k=retrieval_config.get("recall_top_k"),
                similarity_threshold=retrieval_config.get("similarity_threshold"),
                bm25_top_k=retrieval_config.get("bm25_top_k"),
                vector_weight=retrieval_config.get("vector_weight"),
                bm25_weight=retrieval_config.get("bm25_weight"),
                bm25_drop_ratio_search=retrieval_config.get("bm25_drop_ratio_search"),
                include_distances=True,
                use_reranker=retrieval_config.get("use_reranker"),
                reranker_model=retrieval_config.get("reranker_model"),
            )
            question_result = await evaluate_question(
                query=item.query_text,
                gold_chunk_ids=item.gold_chunk_ids or [],
                gold_answer=item.gold_answer,
                retrieved_chunks=query_result.get("results") or [],
                answer_llm=answer_llm,
                judge_llm=judge_llm,
            )

            if question_result["retrieval_scores"]:
                all_retrieval_metrics.append(question_result["retrieval_scores"])
            if question_result["answer_scores"]:
                all_answer_metrics.append(question_result["answer_scores"])

            await self.eval_repo.upsert_run_item(
                run_id=run.run_id,
                item_index=index,
                data={
                    "dataset_item_id": item.item_id,
                    **question_result["detail"],
                },
            )
            await self.eval_repo.update_run(run, {"completed_items": index + 1})

        metrics, overall_score = aggregate_metrics(
            all_retrieval_metrics,
            all_answer_metrics,
            include_overall_score=True,
        )
        await self.eval_repo.update_run(
            run,
            {
                "status": "completed",
                "completed_items": len(items),
                "metrics": metrics,
                "overall_score": overall_score,
                "completed_at": datetime.utcnow(),
            },
        )

    async def list_runs(self, knowledge_base_id: int, user_id: str) -> list[dict[str, Any]]:
        await self._require_base(knowledge_base_id, user_id)
        return [row.to_dict() for row in await self.eval_repo.list_runs(knowledge_base_id, user_id)]

    async def get_run_results(
        self,
        *,
        knowledge_base_id: int,
        user_id: str,
        run_id: str,
        page: int = 1,
        page_size: int = 20,
        error_only: bool = False,
    ) -> dict[str, Any]:
        await self._require_base(knowledge_base_id, user_id)
        run = await self.eval_repo.get_run(run_id)
        if run is None or run.knowledge_base_id != knowledge_base_id or run.user_id != user_id:
            raise ValueError("Run not found")

        if error_only:
            all_items = await self.eval_repo.list_run_items(run_id, offset=0, limit=10000)
            filtered = [item for item in all_items if self._is_error_run_item(item)]
            total = len(filtered)
            page_items = filtered[(page - 1) * page_size : page * page_size]
        else:
            total = await self.eval_repo.count_run_items(run_id)
            page_items = await self.eval_repo.list_run_items(
                run_id,
                offset=(page - 1) * page_size,
                limit=page_size,
            )

        data = run.to_dict()
        data.update(
            {
                "items": [self._run_item_to_dict(item) for item in page_items],
                "pagination": {
                    "current_page": page,
                    "page_size": page_size,
                    "total": total,
                    "total_pages": (total + page_size - 1) // page_size,
                    "error_only": error_only,
                },
            }
        )
        return data

    def _is_error_run_item(self, item: Any) -> bool:
        metrics = item.metrics or {}
        return metrics.get("score", 1.0) <= 0.5 or any(
            metrics.get(key, 1.0) < 0.3 for key in metrics if key.startswith("recall@")
        )

    async def delete_run(self, *, knowledge_base_id: int, user_id: str, run_id: str) -> None:
        run = await self.eval_repo.get_run(run_id)
        if run is None or run.knowledge_base_id != knowledge_base_id or run.user_id != user_id:
            raise ValueError("Run not found")
        await self.eval_repo.delete_run(run)
