import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import KnowledgeBaseRepository, UserSelectionRepository
from app.db.session import get_db
from app.plugins.registry import list_enabled_resources
from app.plugins.types import SelectionIn
from app.repositories.skill_repository import SkillRepository

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{user_id}")
async def get_selection(user_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    item = await UserSelectionRepository(db).get(user_id)
    if item is None:
        return {
            "user_id": user_id,
            "knowledge_base_ids": [],
        }
    return item.to_dict()


@router.put("/{user_id}")
async def save_selection(user_id: str, payload: SelectionIn, db: AsyncSession = Depends(get_db)) -> dict:
    if user_id != payload.user_id:
        raise HTTPException(status_code=400, detail="Path user_id must match payload user_id.")
    # 只持久化当前用户实际拥有的知识库，避免客户端扩大 Agent 查询范围。
    visible_knowledge_bases = await KnowledgeBaseRepository(db).list(user_id)
    visible_ids = {item.id for item in visible_knowledge_bases}
    knowledge_base_ids = list(
        dict.fromkeys(kb_id for kb_id in payload.knowledge_base_ids if kb_id in visible_ids)
    )
    filtered_ids = sorted(set(payload.knowledge_base_ids) - set(knowledge_base_ids))
    if filtered_ids:
        logger.warning(
            "Knowledge base selection filtered: user_id=%s requested_ids=%s filtered_ids=%s",
            user_id,
            payload.knowledge_base_ids,
            filtered_ids,
        )
    item = await UserSelectionRepository(db).save(
        user_id=payload.user_id,
        knowledge_base_ids=knowledge_base_ids,
    )
    logger.info(
        "Knowledge base selection saved: user_id=%s knowledge_base_ids=%s",
        user_id,
        knowledge_base_ids,
    )
    return item.to_dict()


@router.get("/{user_id}/resolved")
async def resolve_selection(user_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    item = await UserSelectionRepository(db).get(user_id)
    data = (
        item.to_dict()
        if item
        else {
            "user_id": user_id,
            "knowledge_base_ids": [],
        }
    )
    return {
        "selection": data,
        "resources": {
            "mcps": await list_enabled_resources(db, kind="mcp", user_id=user_id),
            "skills": [
                skill.to_dict()
                for skill in await SkillRepository(db).list_all()
            ],
            "tools": await list_enabled_resources(db, kind="tool", user_id=user_id),
        },
    }
