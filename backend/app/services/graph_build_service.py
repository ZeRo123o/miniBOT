from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.models import KnowledgeBase
from app.db.repositories import KnowledgeBaseRepository
from app.db.session import AsyncSessionLocal
from app.knowledge.graphs.milvus_graph_service import GRAPH_TASK_TYPE, MilvusGraphService

logger = logging.getLogger(__name__)

GRAPH_TASK_STATE_KEY = "graph_build_task"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class _GraphBuildContext:
    """把图服务进度回写到知识库扩展配置。"""

    def __init__(self, manager: "GraphBuildTaskManager", knowledge_base_id: int, task_id: str) -> None:
        self.manager = manager
        self.knowledge_base_id = knowledge_base_id
        self.task_id = task_id

    async def raise_if_cancelled(self) -> None:
        task = self.manager.tasks.get(self.knowledge_base_id)
        if task is not None and task.cancelled():
            raise asyncio.CancelledError

    async def set_message(self, message: str) -> None:
        await self.manager._update_state(
            self.knowledge_base_id,
            self.task_id,
            message=message,
        )

    async def set_progress(self, progress: float, message: str) -> None:
        await self.manager._update_state(
            self.knowledge_base_id,
            self.task_id,
            progress=max(0, min(round(float(progress)), 100)),
            message=message,
        )

    async def set_result(self, result: dict[str, Any]) -> None:
        await self.manager._update_state(
            self.knowledge_base_id,
            self.task_id,
            result=result,
        )


class GraphBuildTaskManager:
    """在进程内执行图构建，并把任务状态持久化到知识库扩展配置。"""

    def __init__(self) -> None:
        self.tasks: dict[int, asyncio.Task] = {}
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """启动时把上次进程遗留的活动任务标记为失败，避免前端永久等待。"""
        async with AsyncSessionLocal() as db:
            result = await db.execute(select(KnowledgeBase))
            changed = False
            for knowledge_base in result.scalars().all():
                params = dict(knowledge_base.additional_params or {})
                state = dict(params.get(GRAPH_TASK_STATE_KEY) or {})
                if state.get("status") not in {"pending", "running"}:
                    continue
                state.update(
                    status="failed",
                    progress=0,
                    message="服务重启时图谱构建任务中断",
                    completed_at=_utc_now(),
                )
                params[GRAPH_TASK_STATE_KEY] = state
                knowledge_base.additional_params = params
                changed = True
            if changed:
                await db.commit()

    async def submit(
        self,
        *,
        knowledge_base_id: int,
        user_id: str,
        batch_size: int,
    ) -> dict[str, Any]:
        async with self._lock:
            active = self.tasks.get(knowledge_base_id)
            if active is not None and not active.done():
                raise ValueError("该知识库已有正在运行的图谱构建任务。")

            async with AsyncSessionLocal() as db:
                knowledge_base = await KnowledgeBaseRepository(db).get(
                    knowledge_base_id,
                    user_id=user_id,
                )
                if knowledge_base is None:
                    raise LookupError("Knowledge base not found.")
                status = await MilvusGraphService(db).get_status(str(knowledge_base_id))
                if not status["locked"]:
                    raise ValueError("请先确认并锁定图谱抽取配置。")
                if status["pending_chunks"] <= 0:
                    raise ValueError("当前没有待构建图谱的 Chunk。")

            task_id = f"graph_{uuid.uuid4().hex[:12]}"
            state = {
                "task_id": task_id,
                "task_type": GRAPH_TASK_TYPE,
                "status": "pending",
                "progress": 0,
                "message": "等待开始图谱构建",
                "batch_size": int(batch_size),
                "created_by": user_id,
                "created_at": _utc_now(),
            }
            await self._replace_state(knowledge_base_id, task_id, state)
            task = asyncio.create_task(
                self._run(knowledge_base_id, task_id, int(batch_size)),
                name=f"graph-build:{knowledge_base_id}:{task_id}",
            )
            self.tasks[knowledge_base_id] = task
            task.add_done_callback(
                lambda completed, kb_id=knowledge_base_id: self._discard(kb_id, completed)
            )
            return state

    async def _run(self, knowledge_base_id: int, task_id: str, batch_size: int) -> None:
        await self._update_state(
            knowledge_base_id,
            task_id,
            status="running",
            progress=1,
            message="准备构建图谱",
            started_at=_utc_now(),
        )
        try:
            async with AsyncSessionLocal() as db:
                result = await MilvusGraphService(db).build_pending_chunks(
                    str(knowledge_base_id),
                    batch_size=batch_size,
                    context=_GraphBuildContext(self, knowledge_base_id, task_id),
                )
            has_failures = bool(result["failed"] or result["remaining"])
            await self._update_state(
                knowledge_base_id,
                task_id,
                status="failed" if has_failures else "success",
                progress=100,
                message=(
                    f"图谱构建未完全成功，成功 {result['success']} 个，"
                    f"失败 {result['failed']} 个，剩余 {result['remaining']} 个"
                    if has_failures
                    else f"图谱构建完成，成功 {result['success']} 个"
                ),
                result=result,
                error="部分 Chunk 构建失败" if has_failures else None,
                completed_at=_utc_now(),
            )
        except asyncio.CancelledError:
            await self._update_state(
                knowledge_base_id,
                task_id,
                status="cancelled",
                message="图谱构建任务已取消",
                completed_at=_utc_now(),
            )
            raise
        except Exception as error:
            logger.exception("Graph build failed: knowledge_base_id=%s", knowledge_base_id)
            await self._update_state(
                knowledge_base_id,
                task_id,
                status="failed",
                message="图谱构建失败",
                error=str(error),
                completed_at=_utc_now(),
            )

    def _discard(self, knowledge_base_id: int, completed: asyncio.Task) -> None:
        if self.tasks.get(knowledge_base_id) is completed:
            self.tasks.pop(knowledge_base_id, None)
        if not completed.cancelled():
            completed.exception()

    async def _replace_state(
        self,
        knowledge_base_id: int,
        task_id: str,
        state: dict[str, Any],
    ) -> None:
        async with AsyncSessionLocal() as db:
            knowledge_base = await KnowledgeBaseRepository(db).get(knowledge_base_id)
            if knowledge_base is None:
                raise LookupError("Knowledge base not found.")
            params = dict(knowledge_base.additional_params or {})
            params[GRAPH_TASK_STATE_KEY] = state
            knowledge_base.additional_params = params
            await db.commit()

    async def _update_state(
        self,
        knowledge_base_id: int,
        task_id: str,
        **changes: Any,
    ) -> None:
        async with AsyncSessionLocal() as db:
            knowledge_base = await KnowledgeBaseRepository(db).get(knowledge_base_id)
            if knowledge_base is None:
                return
            params = dict(knowledge_base.additional_params or {})
            state = dict(params.get(GRAPH_TASK_STATE_KEY) or {})
            if state.get("task_id") != task_id:
                return
            state.update(changes)
            params[GRAPH_TASK_STATE_KEY] = state
            knowledge_base.additional_params = params
            await db.commit()

    async def stop(self) -> None:
        tasks = [task for task in self.tasks.values() if not task.done()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self.tasks.clear()


graph_build_task_manager = GraphBuildTaskManager()
