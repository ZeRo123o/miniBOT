from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent import AgentRuntime
from app.db.session import get_db
from app.schemas import ChatRequest

router = APIRouter()


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
