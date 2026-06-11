import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import KnowledgeBaseRepository, UserSelectionRepository
from app.db.session import get_db
from app.plugins.registry import list_enabled_resources, resolve_resources_by_name
from app.plugins.types import SelectionIn

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/{user_key}")
async def get_selection(user_key: str, db: AsyncSession = Depends(get_db)) -> dict:
    item = await UserSelectionRepository(db).get(user_key)
    if item is None:
        return {
            "user_key": user_key,
            "mcps": [],
            "skills": [],
            "subagents": [],
            "knowledge_base_ids": [],
        }
    return item.to_dict()


@router.put("/{user_key}")
async def save_selection(user_key: str, payload: SelectionIn, db: AsyncSession = Depends(get_db)) -> dict:
    if user_key != payload.user_key:
        raise HTTPException(status_code=400, detail="Path user_key must match payload user_key.")
    # 只持久化当前用户实际拥有的知识库，避免客户端扩大 Agent 查询范围。
    visible_knowledge_bases = await KnowledgeBaseRepository(db).list(user_key)
    visible_ids = {item.id for item in visible_knowledge_bases}
    knowledge_base_ids = list(
        dict.fromkeys(kb_id for kb_id in payload.knowledge_base_ids if kb_id in visible_ids)
    )
    filtered_ids = sorted(set(payload.knowledge_base_ids) - set(knowledge_base_ids))
    if filtered_ids:
        logger.warning(
            "Knowledge base selection filtered: user_key=%s requested_ids=%s filtered_ids=%s",
            user_key,
            payload.knowledge_base_ids,
            filtered_ids,
        )
    item = await UserSelectionRepository(db).save(
        user_key=payload.user_key,
        mcps=payload.mcps,
        skills=payload.skills,
        subagents=payload.subagents,
        knowledge_base_ids=knowledge_base_ids,
    )
    logger.info(
        "Knowledge base selection saved: user_key=%s knowledge_base_ids=%s",
        user_key,
        knowledge_base_ids,
    )
    return item.to_dict()


@router.get("/{user_key}/resolved")
async def resolve_selection(user_key: str, db: AsyncSession = Depends(get_db)) -> dict:
    item = await UserSelectionRepository(db).get(user_key)
    data = (
        item.to_dict()
        if item
        else {
            "user_key": user_key,
            "mcps": [],
            "skills": [],
            "subagents": [],
            "knowledge_base_ids": [],
        }
    )
    return {
        "selection": data,
        "resources": {
            "mcps": await resolve_resources_by_name(
                db, kind="mcp", names=data["mcps"], user_key=user_key
            ),
            "skills": await resolve_resources_by_name(
                db, kind="skill", names=data["skills"], user_key=user_key
            ),
            "subagents": await resolve_resources_by_name(
                db, kind="subagent", names=data["subagents"], user_key=user_key
            ),
            "tools": await list_enabled_resources(db, kind="tool"),
        },
    }
