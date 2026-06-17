import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from starlette.datastructures import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.buildin.chatbot.runtime import AgentRuntime
from app.db.session import get_db
from app.services.attachment_service import save_chat_uploads
from app.schemas import ChatRequest

router = APIRouter()
logger = logging.getLogger(__name__)


def sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


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
        conversation_id = int(raw_conversation_id) if str(raw_conversation_id or "").strip() else None
        files = [
            value
            for key, value in form.multi_items()
            if key == "files" and isinstance(value, UploadFile)
        ]
        if not message or not message.strip():
            raise HTTPException(status_code=422, detail="message is required")
        return (
            ChatRequest(message=str(message), user_id=user_id, conversation_id=conversation_id),
            files,
        )
    payload = ChatRequest.model_validate(await request.json())
    return payload, []


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

