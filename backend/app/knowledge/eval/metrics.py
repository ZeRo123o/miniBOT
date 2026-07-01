import logging
import textwrap
from typing import Any

import json_repair
from langchain_core.messages import HumanMessage

logger = logging.getLogger(__name__)


class RetrievalMetrics:
    """retrieval metrics for gold chunk matching."""

    @staticmethod
    def precision_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
        if not retrieved_ids[:k]:
            return 0.0
        return len(set(retrieved_ids[:k]) & set(relevant_ids)) / k

    @staticmethod
    def recall_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
        if not relevant_ids:
            return 0.0
        return len(set(retrieved_ids[:k]) & set(relevant_ids)) / len(set(relevant_ids))

    @staticmethod
    def f1_score_at_k(retrieved_ids: list[str], relevant_ids: list[str], k: int) -> float:
        precision = RetrievalMetrics.precision_at_k(retrieved_ids, relevant_ids, k)
        recall = RetrievalMetrics.recall_at_k(retrieved_ids, relevant_ids, k)
        if precision + recall == 0:
            return 0.0
        return 2 * precision * recall / (precision + recall)


class AnswerMetrics:
    """Use an LLM judge to compare generated answers with gold answers."""

    @staticmethod
    def _parse_judge_result(content: str) -> dict[str, Any]:
        """Parse judge output even when the model wraps or slightly breaks JSON."""
        cleaned = content.strip()
        if cleaned.startswith("```json"):
            cleaned = cleaned[7:]
        elif cleaned.startswith("```"):
            cleaned = cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3]
        result = json_repair.loads(cleaned.strip())
        if not isinstance(result, dict):
            raise ValueError("Judge output is not a JSON object.")
        return result

    @staticmethod
    async def judge_correctness(
        *,
        query: str,
        generated_answer: str,
        gold_answer: str,
        judge_llm: Any,
    ) -> dict[str, Any]:
        if not generated_answer:
            return {"score": 0.0, "reasoning": "未生成答案"}
        if not gold_answer:
            return {"score": 0.0, "reasoning": "无参考答案"}

        prompt = textwrap.dedent(
            f"""你是一个公正的评判者，请评估AI生成的答案相对于标准答案的准确性。

            问题：{query}

            标准答案：
            {gold_answer}

            AI生成的答案：
            {generated_answer}

            请判断AI生成的答案是否在事实层面与标准答案一致。
            忽略措辞、标点符号或格式上的细微差异。
            只关注核心事实是否准确包含。

            请返回以下JSON格式的结果（不要包含其他文本、Markdown 或注释）：
            {{
                "score": 1.0,
                "reasoning": "简要说明判定理由"
            }}
            score 只能是 1.0 或 0.0。
            """
        )
        try:
            response = await judge_llm.ainvoke([HumanMessage(content=prompt)])
            content = str(response.content or "").strip()
            result = AnswerMetrics._parse_judge_result(content)
            return {
                "score": 1.0 if float(result.get("score", 0.0)) >= 1.0 else 0.0,
                "reasoning": str(result.get("reasoning") or ""),
            }
        except Exception as error:
            logger.warning("LLM judge failed: %s", error)
            return {"score": 0.0, "reasoning": f"评判出错: {error}"}


class EvaluationMetricsCalculator:
    @staticmethod
    def calculate_retrieval_metrics(
        retrieved_chunks: list[dict[str, Any]],
        gold_chunk_ids: list[str],
        k_values: list[int] | None = None,
    ) -> dict[str, float]:
        if not retrieved_chunks or not gold_chunk_ids:
            return {}

        retrieved_ids = []
        for chunk in retrieved_chunks:
            metadata = chunk.get("metadata") or {}
            chunk_id = chunk.get("chunk_id") or metadata.get("chunk_id")
            if chunk_id is not None:
                retrieved_ids.append(str(chunk_id))

        metrics = {}
        for k in k_values or [1, 3, 5, 10]:
            metrics[f"recall@{k}"] = RetrievalMetrics.recall_at_k(retrieved_ids, gold_chunk_ids, k)
            metrics[f"f1@{k}"] = RetrievalMetrics.f1_score_at_k(retrieved_ids, gold_chunk_ids, k)
        return metrics

    @staticmethod
    async def calculate_answer_metrics(
        *,
        query: str,
        generated_answer: str,
        gold_answer: str,
        judge_llm: Any | None = None,
    ) -> dict[str, Any]:
        if judge_llm is None:
            return {}
        return await AnswerMetrics.judge_correctness(
            query=query,
            generated_answer=generated_answer,
            gold_answer=gold_answer,
            judge_llm=judge_llm,
        )

    @staticmethod
    def calculate_overall_score(
        retrieval_metrics_list: list[dict[str, float]],
        answer_metrics_list: list[dict[str, Any]],
    ) -> float | None:
        if answer_metrics_list:
            scores = [float(item.get("score", 0.0)) for item in answer_metrics_list]
            return sum(scores) / len(scores) if scores else None

        recalls = [item["recall@10"] for item in retrieval_metrics_list if "recall@10" in item]
        return sum(recalls) / len(recalls) if recalls else None
