import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.buildin.chatbot.runtime import AgentRuntime
from app.db.session import get_db
from app.db.repositories import AgentRunRepository
from app.services.chat_run_service import (
    ChatRunConflictError,
    create_chat_run,
    iter_chat_run_events,
)
from app.services.attachment_service import save_chat_uploads
from app.schemas import ChatRequest

router = APIRouter()
logger = logging.getLogger(__name__)


def sse_event(data: dict, *, event_id: str | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id else ""
    return f"{prefix}data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("")
async def chat(payload: ChatRequest, db: AsyncSession = Depends(get_db)) -> dict:
    logger.info(
        "Chat request received: user_id=%s conversation_id=%s message_chars=%s",
        payload.user_id,
        payload.conversation_id,
        len(payload.message),
    )
    runtime = AgentRuntime(db)
    try:
        response = await runtime.run(
            user_id=payload.user_id,
            message=payload.message,
            conversation_id=payload.conversation_id,
            model_spec=payload.model_spec,
            uploads=[item.model_dump() for item in payload.uploads],
        )
        logger.info(
            "Chat request completed: user_id=%s conversation_id=%s",
            payload.user_id,
            response.get("conversation_id"),
        )
        return response
    except ValueError as error:
        logger.warning(
            "Chat request rejected: user_id=%s conversation_id=%s error=%s",
            payload.user_id,
            payload.conversation_id,
            error,
        )
        raise HTTPException(status_code=404, detail=str(error)) from error
    except Exception:
        logger.exception(
            "Chat request failed: user_id=%s conversation_id=%s",
            payload.user_id,
            payload.conversation_id,
        )
        raise


async def _parse_stream_payload(
    request: Request,
) -> tuple[ChatRequest, list[UploadFile]]:
    content_type = request.headers.get("content-type", "")
    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        message = form.get("message")
        user_id = str(form.get("user_id") or "default")
        raw_conversation_id = form.get("conversation_id")
        model_spec = str(form.get("model_spec") or "").strip() or None
        request_id = str(form.get("request_id") or "").strip() or None
        conversation_id = int(raw_conversation_id) if str(raw_conversation_id or "").strip() else None
        files = [
            value
            for key, value in form.multi_items()
            if key == "files" and isinstance(value, UploadFile)
        ]
        if not message or not message.strip():
            raise HTTPException(status_code=422, detail="message is required")
        return (
            ChatRequest(
                message=str(message),
                user_id=user_id,
                conversation_id=conversation_id,
                model_spec=model_spec,
                request_id=request_id,
            ),
            files,
        )
    payload = ChatRequest.model_validate(await request.json())
    return payload, []


@router.post("/runs")
async def create_run(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Create an asynchronous chat run whose lifetime is independent from the browser."""
    payload, upload_files = await _parse_stream_payload(request)
    try:
        return await create_chat_run(payload=payload, upload_files=upload_files, db=db)
    except ChatRunConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/runs/{run_id}")
async def get_run(
    run_id: str,
    user_id: str = Query(default="default", min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = await AgentRunRepository(db).get(run_id, user_id=user_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    return {"run": run.to_dict()}


@router.get("/conversations/{conversation_id}/active-run")
async def get_active_run(
    conversation_id: int,
    user_id: str = Query(default="default", min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> dict:
    run = await AgentRunRepository(db).get_active_chat_run(
        conversation_id=conversation_id,
        user_id=user_id,
    )
    return {"run": run.to_dict() if run else None}


@router.get("/runs/{run_id}/events")
async def run_events(
    run_id: str,
    user_id: str = Query(default="default", min_length=1, max_length=128),
    after: str = Query(default="0-0"),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    run = await AgentRunRepository(db).get(run_id, user_id=user_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found.")
    cursor = (last_event_id or after or "0-0").strip()

    async def event_generator() -> AsyncIterator[str]:
        async for event_id, event in iter_chat_run_events(
            run_id=run_id,
            user_id=user_id,
            after_id=cursor,
        ):
            if event is None:
                yield ": heartbeat\n\n"
            else:
                yield sse_event(event, event_id=event_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/stream")
async def chat_stream(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    payload, upload_files = await _parse_stream_payload(request)

    async def event_generator() -> AsyncIterator[str]:
        logger.info(
            "Chat stream opened: user_id=%s conversation_id=%s message_chars=%s",
            payload.user_id,
            payload.conversation_id,
            len(payload.message),
        )
        runtime = AgentRuntime(db)
        try:
            conversation = await runtime.conversation_service.prepare_conversation(
                user_id=payload.user_id,
                message=payload.message,
                conversation_id=payload.conversation_id,
            )
            uploads = await save_chat_uploads(
                user_id=payload.user_id,
                conversation_id=conversation.id,
                files=upload_files,
            )
            payload.conversation_id = conversation.id
            async for event in runtime.run_stream(
                user_id=payload.user_id,
                message=payload.message,
                conversation_id=payload.conversation_id,
                uploads=[item.model_dump() for item in payload.uploads] + uploads,
                model_spec=payload.model_spec,
            ):
                yield sse_event(event)
            logger.info(
                "Chat stream completed: user_id=%s",
                payload.user_id,
            )
        except ValueError as error:
            logger.warning(
                "Chat stream rejected: user_id=%s conversation_id=%s error=%s",
                payload.user_id,
                payload.conversation_id,
                error,
            )
            yield sse_event({"type": "error", "detail": str(error)})
        except HTTPException as error:
            logger.warning(
                "Chat stream rejected: user_id=%s conversation_id=%s error=%s",
                payload.user_id,
                payload.conversation_id,
                error.detail,
            )
            yield sse_event({"type": "error", "detail": str(error.detail)})
        except Exception as error:
            logger.exception(
                "Chat stream failed: user_id=%s conversation_id=%s",
                payload.user_id,
                payload.conversation_id,
            )
            yield sse_event({"type": "error", "detail": str(error)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

