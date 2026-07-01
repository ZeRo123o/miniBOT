from typing import Any

from langchain_core.messages import HumanMessage

from app.knowledge.eval.metrics import EvaluationMetricsCalculator


def build_answer_prompt(query: str, retrieved_chunks: list[dict[str, Any]], max_docs: int = 5) -> str:
    context_docs = []
    for index, chunk in enumerate(retrieved_chunks[:max_docs]):
        content = str(chunk.get("content") or "").strip()
        if content:
            context_docs.append(f"文档 {index + 1}:\n{content}")

    context_text = "\n\n".join(context_docs)
    return (
        "基于以下上下文信息，请回答用户的问题。\n\n"
        f"上下文信息：{context_text}\n\n"
        f"用户问题：{query}\n\n"
        "请根据上下文信息准确回答问题。\n\n"
        "如果上下文中缺少相关信息，请回答“信息不足，无法回答”。\n\n"
    )


async def generate_answer_if_needed(
    *,
    query: str,
    generated_answer: str,
    retrieved_chunks: list[dict[str, Any]],
    answer_llm: Any | None,
) -> str:
    if generated_answer:
        return generated_answer
    if not retrieved_chunks or answer_llm is None:
        return ""

    response = await answer_llm.ainvoke([HumanMessage(content=build_answer_prompt(query, retrieved_chunks))])
    return str(response.content or "")


async def evaluate_question(
    *,
    query: str,
    gold_chunk_ids: list[str],
    gold_answer: str | None,
    retrieved_chunks: list[dict[str, Any]],
    generated_answer: str = "",
    answer_llm: Any | None = None,
    judge_llm: Any | None = None,
) -> dict[str, Any]:
    generated_answer = await generate_answer_if_needed(
        query=query,
        generated_answer=generated_answer,
        retrieved_chunks=retrieved_chunks,
        answer_llm=answer_llm,
    )

    metrics: dict[str, Any] = {}
    retrieval_scores: dict[str, float] = {}
    answer_scores: dict[str, Any] = {}

    if gold_chunk_ids:
        retrieval_scores = EvaluationMetricsCalculator.calculate_retrieval_metrics(
            retrieved_chunks,
            [str(item) for item in gold_chunk_ids],
        )
        metrics.update(retrieval_scores)

    if gold_answer:
        answer_scores = await EvaluationMetricsCalculator.calculate_answer_metrics(
            query=query,
            generated_answer=generated_answer,
            gold_answer=gold_answer,
            judge_llm=judge_llm,
        )
        metrics.update(answer_scores)

    return {
        "detail": {
            "query_text": query,
            "gold_chunk_ids": gold_chunk_ids,
            "gold_answer": gold_answer,
            "generated_answer": generated_answer,
            "retrieved_chunks": retrieved_chunks,
            "metrics": metrics,
        },
        "retrieval_scores": retrieval_scores,
        "answer_scores": answer_scores,
    }


def aggregate_metrics(
    retrieval_metrics_list: list[dict[str, float]],
    answer_metrics_list: list[dict[str, Any]],
    *,
    include_overall_score: bool = False,
) -> tuple[dict[str, Any], float | None]:
    metrics: dict[str, Any] = {}

    if retrieval_metrics_list:
        keys = sorted({key for item in retrieval_metrics_list for key in item})
        for key in keys:
            metrics[key] = sum(float(item.get(key, 0.0)) for item in retrieval_metrics_list) / len(
                retrieval_metrics_list
            )

    if answer_metrics_list:
        scores = [float(item.get("score", 0.0)) for item in answer_metrics_list]
        metrics["answer_correctness"] = sum(scores) / len(scores) if scores else 0.0

    overall_score = EvaluationMetricsCalculator.calculate_overall_score(
        retrieval_metrics_list,
        answer_metrics_list,
    )
    if include_overall_score:
        metrics["overall_score"] = overall_score
    return metrics, overall_score
