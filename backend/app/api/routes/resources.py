from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import PluginResourceRepository
from app.db.session import get_db
from app.plugins.types import PluginResourceIn

router = APIRouter()


@router.get("")
async def list_resources(
    kind: str | None = Query(default=None, pattern="^(mcp|skill|subagent)$"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    items = await PluginResourceRepository(db).list(kind=kind)
    return [item.to_dict() for item in items]


@router.post("")
async def upsert_resource(payload: PluginResourceIn, db: AsyncSession = Depends(get_db)) -> dict:
    item = await PluginResourceRepository(db).upsert(payload.model_dump())
    return item.to_dict()
