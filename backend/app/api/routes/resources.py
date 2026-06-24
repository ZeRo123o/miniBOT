from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories import PluginResourceRepository
from app.db.session import get_db
from app.plugins.types import PluginResourceIn

router = APIRouter()


def _is_builtin_resource(config: dict) -> bool:
    """Builtin resources are identified exclusively by their stable origin."""
    return config.get("origin") == "builtin"


@router.get("")
async def list_resources(
    kind: str | None = Query(default=None, pattern="^(mcp|tool)$"),
    db: AsyncSession = Depends(get_db),
) -> list[dict]:
    items = await PluginResourceRepository(db).list(kind=kind)
    return [item.to_dict() for item in items]


@router.post("")
async def upsert_resource(payload: PluginResourceIn, db: AsyncSession = Depends(get_db)) -> dict:
    repo = PluginResourceRepository(db)
    data = payload.model_dump()
    existing = await repo.get_by_name(data["kind"], data["name"])
    if existing and _is_builtin_resource(existing.config or {}):
        # Builtins are system-managed and always selected at graph construction.
        data["enabled"] = True
        data["config"] = dict(existing.config or {})
    else:
        data["config"].pop("origin", None)
    item = await repo.upsert(data)
    return item.to_dict()
