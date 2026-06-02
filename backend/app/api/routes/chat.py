import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import AgentRuntime
from app.db.session import get_db
from app.schemas import ChatRequest

router = APIRouter()


def sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("")
async def chat(payload: ChatRequest, db: AsyncSession = Depends(get_db)) -> dict:
    try:
        return await AgentRuntime(db).run(
            user_key=payload.user_key,
            message=payload.message,
            conversation_id=payload.conversation_id,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error


@router.post("/stream")
async def chat_stream(payload: ChatRequest, db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    async def event_generator() -> AsyncIterator[str]:
        try:
            async for event in AgentRuntime(db).run_stream(
                user_key=payload.user_key,
                message=payload.message,
                conversation_id=payload.conversation_id,
            ):
                yield sse_event(event)
        except ValueError as error:
            yield sse_event({"type": "error", "detail": str(error)})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
