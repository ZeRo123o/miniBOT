from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import ConversationMessageRepository, ConversationRepository
from app.db.session import get_db
from app.schemas import ConversationCreate, ConversationMessageCreate, ConversationUpdate

router = APIRouter()


@router.get("")
async def list_conversations(
    user_key: str = Query(default="default", min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    items = await ConversationRepository(db).list(user_key=user_key)
    return [item.to_dict() for item in items]


@router.post("")
async def create_conversation(payload: ConversationCreate, db: AsyncSession = Depends(get_db)) -> dict:
    item = await ConversationRepository(db).create(user_key=payload.user_key, title=payload.title)
    return item.to_dict()


@router.patch("/{conversation_id}")
async def update_conversation(
    conversation_id: int,
    payload: ConversationUpdate,
    user_key: str = Query(default="default", min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> dict:
    repo = ConversationRepository(db)
    item = await repo.get(conversation_id, user_key=user_key)
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    item = await repo.update(item, title=payload.title, archived=payload.archived)
    return item.to_dict()


@router.delete("/{conversation_id}")
async def archive_conversation(
    conversation_id: int,
    user_key: str = Query(default="default", min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> dict:
    repo = ConversationRepository(db)
    item = await repo.get(conversation_id, user_key=user_key)
    if item is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    item = await repo.update(item, archived=True)
    return item.to_dict()


@router.get("/{conversation_id}/messages")
async def list_messages(
    conversation_id: int,
    user_key: str = Query(default="default", min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    conversation = await ConversationRepository(db).get(conversation_id, user_key=user_key)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    items = await ConversationMessageRepository(db).list(conversation_id)
    return [item.to_dict() for item in items]


@router.post("/{conversation_id}/messages")
async def create_message(
    conversation_id: int,
    payload: ConversationMessageCreate,
    user_key: str = Query(default="default", min_length=1, max_length=128),
    db: AsyncSession = Depends(get_db),
) -> dict:
    conversation = await ConversationRepository(db).get(conversation_id, user_key=user_key)
    if conversation is None:
        raise HTTPException(status_code=404, detail="Conversation not found.")
    item = await ConversationMessageRepository(db).create(
        conversation_id=conversation_id,
        role=payload.role,
        content=payload.content,
        metadata=payload.metadata,
    )
    await ConversationRepository(db).touch(conversation)
    return item.to_dict()
