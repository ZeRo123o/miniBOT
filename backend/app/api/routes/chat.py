import json
import logging
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.buildin.chatbot.runtime import AgentRuntime
from app.db.session import get_db
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


@router.post("/stream")
async def chat_stream(payload: ChatRequest, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        logger.info(
            "Chat stream opened: user_id=%s conversation_id=%s message_chars=%s",
            payload.user_id,
            payload.conversation_id,
            len(payload.message),
        )
        runtime = AgentRuntime(db)
        try:
            async for event in runtime.run_stream(
                user_id=payload.user_id,
                message=payload.message,
                conversation_id=payload.conversation_id,
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

