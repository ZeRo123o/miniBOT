"""Durable browser-independent chat runs with replayable Redis Stream events."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import suppress
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.buildin.chatbot.runtime import AgentRuntime
from app.agents.middlewares.subagent_middleware import finish_run, make_parent_thread_id
from app.core.config import get_settings
from app.db.repositories import AgentRunRepository, ConversationRepository
from app.db.session import AsyncSessionLocal
from app.schemas import ChatRequest
from app.services.attachment_service import save_chat_uploads
from app.storage.redis import create_async_redis_client

logger = logging.getLogger(__name__)
TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled", "interrupted"}


class ChatRunConflictError(RuntimeError):
    """Raised when a conversation already owns an unfinished parent run."""


class ChatRunEventStore:
    """Store sanitized frontend events in a bounded Redis Stream per run."""

    def __init__(self) -> None:
        self._client: Any | None = None

    @staticmethod
    def _key(run_id: str) -> str:
        return f"minibot:chat_run:{run_id}:events"

    async def start(self) -> None:
        if self._client is not None:
            return
        settings = get_settings()
        block_seconds = max(settings.chat_run_sse_block_ms / 1000 + 5, 15)
        self._client = await create_async_redis_client(ping=True, socket_timeout=block_seconds)

    async def close(self) -> None:
        if self._client is None:
            return
        await self._client.aclose()
        self._client = None

    async def publish(self, run_id: str, event: dict[str, Any]) -> str:
        await self.start()
        settings = get_settings()
        event_id = await self._client.xadd(
            self._key(run_id),
            {"data": json.dumps(event, ensure_ascii=False, separators=(",", ":"))},
            maxlen=settings.chat_run_event_max_entries,
            approximate=True,
        )
        await self._client.expire(self._key(run_id), settings.chat_run_event_ttl_seconds)
        return str(event_id)

    async def read(self, run_id: str, after_id: str) -> list[tuple[str, dict[str, Any]]]:
        await self.start()
        settings = get_settings()
        rows = await self._client.xread(
            {self._key(run_id): after_id or "0-0"},
            count=200,
            block=settings.chat_run_sse_block_ms,
        )
        events: list[tuple[str, dict[str, Any]]] = []
        for _stream_name, entries in rows:
            for event_id, fields in entries:
                raw = fields.get("data")
                if not raw:
                    continue
                events.append((str(event_id), json.loads(raw)))
        return events


chat_run_events = ChatRunEventStore()


class ChatRunManager:
    """Execute chat runs independently from their SSE subscribers."""

    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}
        self._semaphore: asyncio.Semaphore | None = None
        self._started = False

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._semaphore = asyncio.Semaphore(get_settings().chat_run_max_concurrency)
        await chat_run_events.start()

        # Pending work never started and is safe to enqueue. A running task from a prior
        # process cannot be resumed without risking duplicate graph input, so mark it interrupted.
        async with AsyncSessionLocal() as db:
            repository = AgentRunRepository(db)
            stale_runs = await repository.list_chat_runs_by_status(["running"])
            for run in stale_runs:
                await repository.set_terminal_status(
                    run.id,
                    status="interrupted",
                    error_type="ServerRestarted",
                    error_message="The backend restarted while this run was active.",
                )
            pending_runs = await repository.list_chat_runs_by_status(["pending"])
        for run in pending_runs:
            self.enqueue(run.id)

    async def stop(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        await chat_run_events.close()
        self._started = False

    def enqueue(self, run_id: str) -> None:
        if run_id in self._tasks:
            return
        task = asyncio.create_task(self._execute(run_id), name=f"chat-run:{run_id}")
        self._tasks[run_id] = task
        task.add_done_callback(lambda _task: self._tasks.pop(run_id, None))

    async def _execute(self, run_id: str) -> None:
        if self._semaphore is None:
            raise RuntimeError("Chat run manager has not started.")
        async with self._semaphore:
            try:
                async with AsyncSessionLocal() as db:
                    repository = AgentRunRepository(db)
                    run = await repository.get(run_id)
                    if run is None or run.status != "pending":
                        return
                    await repository.set_status(run_id, "running")
                    payload = run.input_payload or {}
                    runtime = AgentRuntime(db)
                    final_response: dict[str, Any] = {}
                    async for event in runtime.run_prepared_stream(
                        user_id=run.user_id,
                        message=str(payload.get("message") or ""),
                        conversation_id=run.conversation_id,
                        uploads=list(payload.get("uploads") or []),
                        model_spec=str(payload.get("model_spec") or ""),
                        run_id=run.id,
                    ):
                        if event.get("type") == "done":
                            final_response = event
                        await chat_run_events.publish(run.id, event)

                    final_messages = final_response.get("messages") or []
                    final_metadata = final_messages[-1].get("metadata", {}) if final_messages else {}
                    status = "failed" if final_metadata.get("error") else "completed"
                    await repository.set_terminal_status(
                        run.id,
                        status=status,
                        result_payload={
                            "content": final_response.get("answer") or "",
                            "subagent_runs": final_response.get("subagent_runs") or [],
                        },
                        error_type=final_metadata.get("error"),
                    )
                    await chat_run_events.publish(run.id, {"type": "end", "status": status})
            except asyncio.CancelledError:
                with suppress(Exception):
                    await finish_run(
                        run_id,
                        status="interrupted",
                        error=RuntimeError("Chat run interrupted because the backend is shutting down."),
                    )
                with suppress(Exception):
                    await chat_run_events.publish(run_id, {"type": "end", "status": "interrupted"})
                raise
            except Exception as error:
                logger.exception("Background chat run failed: run_id=%s", run_id)
                with suppress(Exception):
                    await finish_run(run_id, status="failed", error=error)
                with suppress(Exception):
                    await chat_run_events.publish(
                        run_id,
                        {"type": "error", "detail": str(error) or type(error).__name__},
                    )
                    await chat_run_events.publish(run_id, {"type": "end", "status": "failed"})


chat_run_manager = ChatRunManager()


async def create_chat_run(
    *,
    payload: ChatRequest,
    upload_files: list[Any],
    db: AsyncSession,
) -> dict[str, Any]:
    """Persist an idempotent chat turn and enqueue execution before returning to the browser."""
    model_spec = (payload.model_spec or "").strip()
    if not model_spec:
        raise ValueError("请选择聊天模型后再发送消息。")
    request_id = (payload.request_id or str(uuid.uuid4())).strip()
    repository = AgentRunRepository(db)

    existing = await repository.get_by_request_id(request_id)
    if existing is not None:
        if existing.user_id != payload.user_id:
            raise ValueError("Request ID is already owned by another user.")
        return await _build_run_response(existing.to_dict(), db)

    runtime = AgentRuntime(db)
    conversation = await runtime.conversation_service.prepare_conversation(
        user_id=payload.user_id,
        message=payload.message,
        conversation_id=payload.conversation_id,
    )
    active_run = await repository.get_active_chat_run(
        conversation_id=conversation.id,
        user_id=payload.user_id,
    )
    if active_run is not None:
        raise ChatRunConflictError("当前对话仍在生成回答，请等待完成后再发送。")

    uploaded_files = await save_chat_uploads(
        user_id=payload.user_id,
        conversation_id=conversation.id,
        files=upload_files,
    )
    uploads = [item.model_dump() for item in payload.uploads] + uploaded_files
    run_id = str(uuid.uuid4())
    await runtime.conversation_service.save_user_message(
        conversation.id,
        payload.message,
        uploads=uploads,
        request_id=request_id,
        run_id=run_id,
    )
    run = await repository.create(
        {
            "id": run_id,
            "conversation_id": conversation.id,
            "user_id": payload.user_id,
            "thread_id": make_parent_thread_id(conversation.id),
            "agent_id": "chatbot",
            "run_type": "chat",
            "request_id": request_id,
            "checkpoint_thread_id": make_parent_thread_id(conversation.id),
            "status": "pending",
            "input_payload": {
                # The background process needs the exact user input; logs still only record lengths.
                "message": payload.message,
                "model_spec": model_spec,
                "uploads": uploads,
            },
        }
    )
    await db.refresh(conversation)
    conversation_payload = conversation.to_dict()
    chat_run_manager.enqueue(run.id)
    return {
        "run_id": run.id,
        "request_id": run.request_id,
        "status": run.status,
        "conversation_id": conversation.id,
        "conversation": conversation_payload,
        "stream_url": f"/api/chat/runs/{run.id}/events",
    }


async def _build_run_response(run: dict[str, Any], db: AsyncSession) -> dict[str, Any]:
    conversation = await ConversationRepository(db).get(run["conversation_id"], user_id=run["user_id"])
    return {
        "run_id": run["id"],
        "request_id": run["request_id"],
        "status": run["status"],
        "conversation_id": run["conversation_id"],
        "conversation": conversation.to_dict() if conversation else None,
        "stream_url": f"/api/chat/runs/{run['id']}/events",
    }


async def iter_chat_run_events(
    *,
    run_id: str,
    user_id: str,
    after_id: str,
) -> AsyncIterator[tuple[str | None, dict[str, Any] | None]]:
    """Yield replayable run events and heartbeat markers until a terminal event arrives."""
    cursor = after_id or "0-0"
    while True:
        events = await chat_run_events.read(run_id, cursor)
        if events:
            for event_id, event in events:
                cursor = event_id
                yield event_id, event
                if event.get("type") == "end":
                    return
            continue

        async with AsyncSessionLocal() as db:
            run = await AgentRunRepository(db).get(run_id, user_id=user_id)
        if run is None:
            yield None, {"type": "error", "detail": "Run not found."}
            return
        if run.status in TERMINAL_RUN_STATUSES:
            yield None, {"type": "end", "status": run.status}
            return
        yield None, None
