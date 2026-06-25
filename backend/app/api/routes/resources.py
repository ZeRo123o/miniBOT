from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.mcp import (
    clear_mcp_tools_cache,
    discover_mcp_tools,
    mcp_tool_metadata,
    validate_mcp_config,
)
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
    if data["kind"] == "mcp":
        try:
            data["config"] = validate_mcp_config(data["config"])
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
    item = await repo.upsert(data)
    if item.kind == "mcp":
        clear_mcp_tools_cache(item.name)
    return item.to_dict()


async def _get_mcp_resource(name: str, db: AsyncSession):
    resource = await PluginResourceRepository(db).get_by_name("mcp", name)
    if resource is None:
        raise HTTPException(status_code=404, detail=f"MCP resource '{name}' was not found")
    try:
        validate_mcp_config(resource.config or {})
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return resource


@router.post("/{name}/mcp/test")
async def test_mcp_resource(name: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Connect once without using cache, so the management UI can verify a server."""
    resource = await _get_mcp_resource(name, db)
    try:
        tools = await discover_mcp_tools(name, resource.config or {}, force_refresh=True, include_disabled=True)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"name": name, "tool_count": len(tools), "message": "MCP connection succeeded"}


@router.get("/{name}/mcp/tools")
async def list_mcp_resource_tools(name: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Discover a server's tool inventory, including tools disabled by policy."""
    resource = await _get_mcp_resource(name, db)
    try:
        tools = await discover_mcp_tools(name, resource.config or {}, include_disabled=True)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    config = resource.config or {}
    return {"name": name, "tools": mcp_tool_metadata(tools, config.get("disabled_tools") or [])}


@router.post("/{name}/mcp/refresh")
async def refresh_mcp_resource_tools(name: str, db: AsyncSession = Depends(get_db)) -> dict:
    """Invalidate and rediscover one MCP server's tool inventory."""
    resource = await _get_mcp_resource(name, db)
    clear_mcp_tools_cache(name)
    try:
        tools = await discover_mcp_tools(name, resource.config or {}, force_refresh=True, include_disabled=True)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    return {"name": name, "tool_count": len(tools), "message": "MCP tools refreshed"}


@router.put("/{name}/mcp/tools/{tool_name}")
async def set_mcp_tool_enabled(name: str, tool_name: str, enabled: bool, db: AsyncSession = Depends(get_db)) -> dict:
    """Enable or disable one discovered MCP tool while preserving the server resource."""
    resource = await _get_mcp_resource(name, db)
    try:
        tools = await discover_mcp_tools(name, resource.config or {}, include_disabled=True)
    except RuntimeError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error
    if tool_name not in {tool.name for tool in tools}:
        raise HTTPException(status_code=404, detail=f"MCP tool '{tool_name}' was not found on '{name}'")

    config = dict(resource.config or {})
    disabled = {str(value) for value in config.get("disabled_tools") or []}
    if enabled:
        disabled.discard(tool_name)
    else:
        disabled.add(tool_name)
    config["disabled_tools"] = sorted(disabled)
    resource.config = config
    await db.commit()
    await db.refresh(resource)
    clear_mcp_tools_cache(name)
    return {"name": name, "tool_name": tool_name, "enabled": enabled, "resource": resource.to_dict()}
