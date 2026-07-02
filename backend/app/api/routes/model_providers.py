from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.llm.providers.cache import model_cache
from app.llm.providers.repository import get_model_provider, list_model_providers, list_model_use_configs
from app.llm.providers.service import (
    create_provider_config,
    delete_provider_config,
    fetch_remote_models,
    refresh_model_runtime_cache,
    set_model_use_config,
    test_model_status_by_spec,
    update_provider_config,
)

router = APIRouter()


class ModelProviderPayload(BaseModel):
    provider_id: str | None = None
    display_name: str | None = None
    provider_type: str | None = None
    default_protocol: str | None = None
    base_url: str | None = None
    embedding_base_url: str | None = None
    rerank_base_url: str | None = None
    models_endpoint: str | None = None
    embedding_models_endpoint: str | None = None
    rerank_models_endpoint: str | None = None
    api_key_env: str | None = None
    api_key: str | None = None
    capabilities: list[str] | None = None
    enabled_models: list[dict[str, Any]] | None = None
    headers_json: dict[str, Any] | None = None
    extra_json: dict[str, Any] | None = None
    is_enabled: bool | None = None
    is_builtin: bool | None = None


class ModelUsePayload(BaseModel):
    model_spec: str


@router.get("")
async def list_providers(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return [provider.to_dict(mask_api_key=True) for provider in await list_model_providers(db)]


@router.post("")
async def create_provider(payload: ModelProviderPayload, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    try:
        provider = await create_provider_config(db, payload.model_dump(exclude_none=True))
        await db.commit()
        await refresh_model_runtime_cache(db)
        return provider.to_dict(mask_api_key=True)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/models/v2")
async def list_models_v2(
    model_type: str = Query(default="chat", pattern="^(chat|embedding|rerank)$"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    grouped = model_cache.get_specs_grouped_by_provider(model_type)
    providers = {item.provider_id: item for item in await list_model_providers(db)}
    result = {}
    for provider_id, models in grouped.items():
        provider = providers.get(provider_id)
        result[provider_id] = {
            "provider_id": provider_id,
            "provider_display_name": provider.display_name if provider else provider_id,
            "models": [
                {
                    "spec": item.spec,
                    "model_id": item.model_id,
                    "display_name": item.display_name,
                    "dimension": item.dimension,
                    "batch_size": item.batch_size,
                }
                for item in models
            ],
        }
    return result


@router.get("/models/status")
async def get_model_status(spec: str = Query(...)) -> dict[str, Any]:
    return await test_model_status_by_spec(spec)


@router.post("/models/cache/refresh")
async def refresh_model_cache(db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    await refresh_model_runtime_cache(db)
    return {"message": "model cache refreshed", "model_count": len(model_cache.get_all_specs())}


@router.get("/model-uses")
async def list_model_uses(db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    return [item.to_dict() for item in await list_model_use_configs(db)]


@router.put("/model-uses/{model_use}")
async def update_model_use(
    model_use: str,
    payload: ModelUsePayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        item = await set_model_use_config(db, model_use, payload.model_spec)
        await db.commit()
        await refresh_model_runtime_cache(db)
        return item.to_dict()
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.get("/{provider_id}")
async def get_provider(provider_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    provider = await get_model_provider(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"provider {provider_id} was not found")
    return provider.to_dict(mask_api_key=True)


@router.put("/{provider_id}")
async def update_provider(
    provider_id: str,
    payload: ModelProviderPayload,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = payload.model_dump(exclude_none=True)
    for nullable_field in (
        "default_protocol",
        "embedding_base_url",
        "rerank_base_url",
        "models_endpoint",
        "embedding_models_endpoint",
        "rerank_models_endpoint",
        "api_key_env",
        "api_key",
    ):
        if nullable_field in payload.model_fields_set and getattr(payload, nullable_field) is None:
            data[nullable_field] = None
    try:
        provider = await update_provider_config(db, provider_id, data)
        if provider is None:
            raise HTTPException(status_code=404, detail=f"provider {provider_id} was not found")
        await db.commit()
        await refresh_model_runtime_cache(db)
        return provider.to_dict(mask_api_key=True)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@router.delete("/{provider_id}")
async def delete_provider(provider_id: str, db: AsyncSession = Depends(get_db)) -> dict[str, Any]:
    deleted = await delete_provider_config(db, provider_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"provider {provider_id} was not found")
    await db.commit()
    await refresh_model_runtime_cache(db)
    return {"deleted": True}


@router.get("/{provider_id}/remote-models")
async def get_remote_models(provider_id: str, db: AsyncSession = Depends(get_db)) -> list[dict[str, Any]]:
    provider = await get_model_provider(db, provider_id)
    if provider is None:
        raise HTTPException(status_code=404, detail=f"provider {provider_id} was not found")
    try:
        return await fetch_remote_models(provider)
    except httpx.HTTPStatusError as error:
        if error.response.status_code == 401:
            raise HTTPException(status_code=502, detail="remote API authentication failed") from error
        raise HTTPException(status_code=502, detail=error.response.text) from error
    except Exception as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
