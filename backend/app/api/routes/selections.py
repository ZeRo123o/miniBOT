from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import UserSelectionRepository
from app.db.session import get_db
from app.plugins.registry import resolve_resources_by_name
from app.plugins.types import SelectionIn

router = APIRouter()


@router.get("/{user_key}")
async def get_selection(user_key: str, db: AsyncSession = Depends(get_db)) -> dict:
    item = await UserSelectionRepository(db).get(user_key)
    if item is None:
        return {"user_key": user_key, "mcps": [], "skills": [], "subagents": []}
    return item.to_dict()


@router.put("/{user_key}")
async def save_selection(user_key: str, payload: SelectionIn, db: AsyncSession = Depends(get_db)) -> dict:
    if user_key != payload.user_key:
        raise HTTPException(status_code=400, detail="Path user_key must match payload user_key.")
    item = await UserSelectionRepository(db).save(
        user_key=payload.user_key,
        mcps=payload.mcps,
        skills=payload.skills,
        subagents=payload.subagents,
    )
    return item.to_dict()


@router.get("/{user_key}/resolved")
async def resolve_selection(user_key: str, db: AsyncSession = Depends(get_db)) -> dict:
    item = await UserSelectionRepository(db).get(user_key)
    data = item.to_dict() if item else {"user_key": user_key, "mcps": [], "skills": [], "subagents": []}
    return {
        "selection": data,
        "resources": {
            "mcps": await resolve_resources_by_name(db, kind="mcp", names=data["mcps"]),
            "skills": await resolve_resources_by_name(db, kind="skill", names=data["skills"]),
            "subagents": await resolve_resources_by_name(db, kind="subagent", names=data["subagents"]),
        },
    }
