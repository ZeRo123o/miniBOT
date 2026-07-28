from __future__ import annotations

import asyncio
import json
import logging
import random
from collections.abc import AsyncIterator, Callable
from typing import Any

import json_repair
from langchain_core.messages import HumanMessage

from app.knowledge.backends import get_knowledge_backend

logger = logging.getLogger(__name__)

DEFAULT_BENCHMARK_GENERATION_CONCURRENCY = 4
MAX_BENCHMARK_GENERATION_CONCURRENCY = 10
DEFAULT_CONTEXT_COUNT = 3
MAX_CONTEXT_COUNT = 8


def normalize_generation_concurrency_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_BENCHMARK_GENERATION_CONCURRENCY
    return min(max(count, 1), MAX_BENCHMARK_GENERATION_CONCURRENCY)


def clamp_context_count(value: Any) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_CONTEXT_COUNT
    return min(max(count, 1), MAX_CONTEXT_COUNT)


async def select_neighbor_chunks_by_kb_query(
    *,
    knowledge_base_id: int,
    anchor_chunk: dict[str, Any],
    context_count: int,
) -> list[dict[str, Any]]:
    if context_count <= 1:
        return []

    anchor_content = str(anchor_chunk.get("content") or "").strip()
    if not anchor_content:
        return []

    backend = get_knowledge_backend()
    candidates = await backend.query(
        knowledge_base_id=knowledge_base_id,
        query_text=anchor_content,
        search_mode="vector",
        final_top_k=context_count + 3,
        recall_top_k=context_count + 3,
        similarity_threshold=0.0,
        include_distances=False,
    )

    chunks: list[dict[str, Any]] = []
    anchor_id = str(anchor_chunk.get("chunk_id") or anchor_chunk.get("id") or "")
    for candidate in candidates:
        metadata = candidate.get("metadata") or {}
        chunk_id = str(metadata.get("chunk_id") or "")
        content = str(candidate.get("content") or "")
        if not chunk_id or not content or chunk_id == anchor_id:
            continue
        chunks.append(
            {
                "id": chunk_id,
                "chunk_id": chunk_id,
                "content": content,
                "document_id": metadata.get("document_id"),
                "chunk_index": metadata.get("chunk_index"),
            }
        )
        if len(chunks) >= context_count - 1:
            break
    return chunks


def build_benchmark_generation_prompt(ctx_items: list[tuple[str, str]]) -> str:
    context_text = "\n\n".join([f"片段ID={cid}\n{content}" for cid, content in ctx_items])
    return (
        "你将基于以下上下文生成一个可由上下文准确回答的问题与标准答案。"
        "问题应该像真实用户检索知识库时会提出的问题，答案必须完全依据上下文。"
        "仅返回一个JSON对象，不要包含Markdown代码块或其他文字。"
        "键为 query、gold_answer、gold_chunk_ids。"
        "gold_chunk_ids 必须是上述上下文片段的ID子集。\n\n"
        "上下文：\n" + context_text + "\n"
    )


async def _generate_benchmark_item_once(
    *,
    knowledge_base_id: int,
    all_chunks: list[dict[str, Any]],
    llm: Any,
    context_count: int,
) -> dict[str, Any] | None:
    anchor_chunk = all_chunks[random.randrange(len(all_chunks))]
    neighbor_chunks = await select_neighbor_chunks_by_kb_query(
        knowledge_base_id=knowledge_base_id,
        anchor_chunk=anchor_chunk,
        context_count=context_count,
    )
    ctx_chunks = [anchor_chunk, *neighbor_chunks]
    ctx_items = [(str(chunk["chunk_id"]), str(chunk["content"])) for chunk in ctx_chunks if chunk.get("content")]
    allowed_ids = {cid for cid, _ in ctx_items}
    if not ctx_items:
        return None

    try:
        response = await llm.ainvoke([HumanMessage(content=build_benchmark_generation_prompt(ctx_items))])
        obj = json_repair.loads(str(response.content if response else ""))
        query = str(obj.get("query") or "").strip()
        answer = str(obj.get("gold_answer") or "").strip()
        gold_ids = obj.get("gold_chunk_ids")
        if not query or not answer or not isinstance(gold_ids, list):
            logger.warning("Generated benchmark JSON missing fields or invalid format: %s", obj)
            return None

        normalized_gold_ids = [str(item) for item in gold_ids if str(item) in allowed_ids]
        if not normalized_gold_ids:
            logger.warning("Generated benchmark gold_chunk_ids not found in allowed context")
            return None

        return {"query": query, "gold_chunk_ids": normalized_gold_ids, "gold_answer": answer}
    except Exception as error:
        logger.warning("Benchmark generation failed for one item: %s", error)
        return None


async def iter_generated_benchmark_items(
    *,
    knowledge_base_id: int,
    all_chunks: list[dict[str, Any]],
    count: int,
    context_count: int = DEFAULT_CONTEXT_COUNT,
    llm: Any,
    concurrency_count: int = DEFAULT_BENCHMARK_GENERATION_CONCURRENCY,
    progress_cb: Callable[[int, str], Any] | None = None,
) -> AsyncIterator[dict[str, Any]]:
    if not all_chunks:
        raise ValueError("No chunks found in knowledge base")
    if count <= 0:
        raise ValueError("count must be greater than 0")

    context_count = clamp_context_count(context_count)
    max_attempts = max(count * 5, 20)
    worker_count = min(normalize_generation_concurrency_count(concurrency_count), count)
    generated = 0
    results: list[tuple[int, dict[str, Any]]] = []
    state_lock = asyncio.Lock()
    queue: asyncio.Queue[int] = asyncio.Queue()
    for attempt_no in range(max_attempts):
        queue.put_nowait(attempt_no)

    async def worker() -> None:
        nonlocal generated
        while True:
            async with state_lock:
                if generated >= count:
                    return
            try:
                attempt_no = queue.get_nowait()
            except asyncio.QueueEmpty:
                return
            try:
                item = await _generate_benchmark_item_once(
                    knowledge_base_id=knowledge_base_id,
                    all_chunks=all_chunks,
                    llm=llm,
                    context_count=context_count,
                )
                if item is None:
                    continue
                progress = None
                message = None
                async with state_lock:
                    if generated >= count:
                        continue
                    generated += 1
                    results.append((attempt_no, item))
                    if progress_cb:
                        progress = int(99 * generated / max(count, 1))
                        message = f"已生成 {generated}/{count}"
                if progress_cb and progress is not None and message is not None:
                    await progress_cb(progress, message)
            finally:
                queue.task_done()

    workers = [asyncio.create_task(worker()) for _ in range(worker_count)]
    try:
        await asyncio.gather(*workers)
    except Exception:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise

    for _, item in sorted(results, key=lambda pair: pair[0]):
        yield item


def dump_benchmark_item(item: dict[str, Any]) -> str:
    return json.dumps(item, ensure_ascii=False, separators=(",", ":")) + "\n"
