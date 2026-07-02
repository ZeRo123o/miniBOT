from __future__ import annotations

import asyncio
import os
import re
from typing import Any

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelProvider
from app.llm.providers.builtin import BUILTIN_PROVIDERS
from app.llm.providers.repository import (
    create_model_provider,
    delete_model_provider,
    get_model_provider,
    list_model_providers,
    list_model_use_configs,
    update_model_provider,
    upsert_model_use_config,
)

VALID_MODEL_TYPES = {"chat", "embedding", "rerank"}
VALID_MODEL_SOURCES = {"manual", "remote"}
VALID_PROVIDER_TYPES = {"mock", "openai", "anthropic", "gemini", "openrouter"}
VALID_MODEL_USES = {"chat_model", "deep_research_model"}
PROVIDER_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{1,99}$")


def _normalize_list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _normalize_dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _validate_provider_id(provider_id: str) -> None:
    if not PROVIDER_ID_RE.match(provider_id):
        raise ValueError("provider_id can only contain letters, numbers, underscores and hyphens")


def _normalize_model_item(model: dict[str, Any]) -> dict[str, Any]:
    model_id = str(model.get("id") or "").strip()
    if not model_id:
        raise ValueError("model id cannot be empty")
    model_type = str(model.get("type") or "chat").strip()
    if model_type not in VALID_MODEL_TYPES:
        raise ValueError(f"model {model_id} type must be one of {sorted(VALID_MODEL_TYPES)}")
    source = str(model.get("source") or "manual").strip()
    if source not in VALID_MODEL_SOURCES:
        raise ValueError(f"model {model_id} source must be manual or remote")

    normalized = dict(model)
    normalized["id"] = model_id
    normalized["type"] = model_type
    normalized["source"] = source
    normalized["display_name"] = str(model.get("display_name") or model.get("name") or model_id)
    normalized["extra"] = _normalize_dict(model.get("extra"))
    if model_type == "embedding":
        if model.get("dimension") not in (None, ""):
            normalized["dimension"] = int(model["dimension"])
        if model.get("batch_size") not in (None, ""):
            normalized["batch_size"] = int(model["batch_size"])
    return normalized


def _normalize_model_list(models: Any) -> list[dict[str, Any]]:
    normalized_models = []
    seen: set[tuple[str, str]] = set()
    for item in _normalize_list(models):
        if not isinstance(item, dict):
            raise ValueError("enabled_models must be a list of objects")
        normalized = _normalize_model_item(item)
        key = (normalized["id"], normalized["type"])
        if key in seen:
            raise ValueError(f"duplicate model id/type: {normalized['id']} ({normalized['type']})")
        seen.add(key)
        normalized_models.append(normalized)
    return normalized_models


def _validate_model_capabilities(enabled_models: list[dict[str, Any]], capabilities: set[str]) -> None:
    if not capabilities:
        return
    for model in enabled_models:
        if model["type"] not in capabilities:
            raise ValueError(f"model {model['id']} type={model['type']} is outside provider capabilities")


def normalize_provider_payload(data: dict[str, Any], *, partial: bool = False) -> dict[str, Any]:
    payload = dict(data)
    if not partial or "provider_id" in payload:
        provider_id = str(payload.get("provider_id") or "").strip()
        _validate_provider_id(provider_id)
        payload["provider_id"] = provider_id
    if not partial or "display_name" in payload:
        display_name = str(payload.get("display_name") or "").strip()
        if not display_name:
            raise ValueError("display_name cannot be empty")
        payload["display_name"] = display_name
    if not partial or "base_url" in payload:
        base_url = str(payload.get("base_url") or "").strip()
        if not base_url:
            raise ValueError("base_url cannot be empty")
        payload["base_url"] = base_url

    if not partial and "provider_type" not in payload:
        payload["provider_type"] = "openai"
    if "provider_type" in payload and payload["provider_type"] not in VALID_PROVIDER_TYPES:
        raise ValueError(f"provider_type must be one of {sorted(VALID_PROVIDER_TYPES)}")

    defaults = {
        "capabilities": [],
        "enabled_models": [],
        "headers_json": {},
        "extra_json": {},
        "is_enabled": True,
        "is_builtin": False,
    }
    normalizers = {
        "capabilities": _normalize_list,
        "enabled_models": _normalize_model_list,
        "headers_json": _normalize_dict,
        "extra_json": _normalize_dict,
        "is_enabled": bool,
        "is_builtin": bool,
    }
    for field, default in defaults.items():
        if field in payload:
            payload[field] = normalizers[field](payload[field])
        elif not partial:
            payload[field] = default

    if "capabilities" in payload and "enabled_models" in payload:
        _validate_model_capabilities(payload["enabled_models"], set(payload["capabilities"]))

    for field in (
        "default_protocol",
        "embedding_base_url",
        "rerank_base_url",
        "models_endpoint",
        "embedding_models_endpoint",
        "rerank_models_endpoint",
        "api_key_env",
        "api_key",
    ):
        if field in payload and payload[field] == "":
            payload[field] = None
    return payload


def resolve_api_key(provider: ModelProvider) -> str | None:
    if provider.api_key:
        return provider.api_key
    if provider.api_key_env:
        return os.getenv(provider.api_key_env)
    return None


async def ensure_builtin_model_providers_in_db(db: AsyncSession) -> None:
    existing = {item.provider_id: item for item in await list_model_providers(db)}
    for provider_def in BUILTIN_PROVIDERS:
        provider_id = provider_def["provider_id"]
        current = existing.get(provider_id)
        if current:
            if not current.enabled_models and provider_def.get("enabled_models"):
                current.enabled_models = _normalize_model_list(provider_def["enabled_models"])
                current.capabilities = provider_def.get("capabilities") or current.capabilities
                current.updated_by = "system"
                await db.flush()
            continue
        payload = normalize_provider_payload({**provider_def, "is_builtin": True, "created_by": "system", "updated_by": "system"})
        payload["is_enabled"] = provider_id == "mock"
        await create_model_provider(db, payload)

    await db.commit()


async def refresh_model_runtime_cache(db: AsyncSession) -> None:
    from app.llm.providers.cache import model_cache

    providers = await list_model_providers(db)
    model_uses = await list_model_use_configs(db)
    model_cache.rebuild(providers, model_uses)


async def create_provider_config(db: AsyncSession, data: dict[str, Any], username: str = "default") -> ModelProvider:
    payload = normalize_provider_payload(data)
    if await get_model_provider(db, payload["provider_id"]):
        raise ValueError(f"provider {payload['provider_id']} already exists")
    payload["created_by"] = username
    payload["updated_by"] = username
    return await create_model_provider(db, payload)


async def update_provider_config(
    db: AsyncSession,
    provider_id: str,
    data: dict[str, Any],
    username: str = "default",
) -> ModelProvider | None:
    provider = await get_model_provider(db, provider_id)
    if provider is None:
        return None
    payload = normalize_provider_payload(data, partial=True)
    if "enabled_models" in payload and "capabilities" not in payload:
        _validate_model_capabilities(payload["enabled_models"], set(provider.capabilities or []))
    payload["updated_by"] = username
    return await update_model_provider(db, provider, payload)


async def delete_provider_config(db: AsyncSession, provider_id: str) -> bool:
    provider = await get_model_provider(db, provider_id)
    if provider is None:
        return False
    await delete_model_provider(db, provider)
    return True


async def set_model_use_config(db: AsyncSession, model_use: str, model_spec: str):
    if model_use not in VALID_MODEL_USES:
        raise ValueError(f"model_use must be one of {sorted(VALID_MODEL_USES)}")
    if not model_spec or ":" not in model_spec:
        raise ValueError("model_spec must use provider_id:model_id format")
    return await upsert_model_use_config(db, model_use, model_spec)


def _models_url(base_url: str, endpoint: str | None) -> str:
    if not endpoint:
        return base_url.rstrip("/")
    if endpoint.startswith(("http://", "https://")):
        return endpoint
    return f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"


def _url_with_endpoint(base_url: str, endpoint: str) -> str:
    """Append an API endpoint unless the configured base URL already points to it."""
    normalized_base = base_url.rstrip("/")
    normalized_endpoint = endpoint.strip("/")
    if normalized_base.endswith(f"/{normalized_endpoint}"):
        return normalized_base
    return f"{normalized_base}/{normalized_endpoint}"


def _remote_model_dimension(raw: dict[str, Any]) -> int | None:
    for key in ("dimension", "dimensions", "embedding_dimension", "dim"):
        value = raw.get(key)
        if value not in (None, ""):
            try:
                return int(value)
            except (TypeError, ValueError):
                return None
    return None


def _normalize_remote_model(raw: dict[str, Any], model_type: str) -> dict[str, Any]:
    model_id = str(raw.get("id") or "").strip()
    if not model_id:
        return {}
    architecture = _normalize_dict(raw.get("architecture"))
    top_provider = _normalize_dict(raw.get("top_provider"))
    raw_type = raw.get("type")
    normalized_type = raw_type if raw_type in VALID_MODEL_TYPES else model_type
    return {
        "id": model_id,
        "object": raw.get("object"),
        "created": raw.get("created"),
        "owned_by": raw.get("owned_by"),
        "type": normalized_type,
        "source": "remote",
        "display_name": raw.get("name") or model_id,
        "description": raw.get("description"),
        "dimension": _remote_model_dimension(raw),
        "context_length": raw.get("context_length") or top_provider.get("context_length"),
        "max_completion_tokens": top_provider.get("max_completion_tokens"),
        "input_modalities": architecture.get("input_modalities") or [],
        "output_modalities": architecture.get("output_modalities") or [],
        "supported_parameters": raw.get("supported_parameters") or [],
        "pricing": raw.get("pricing") or {},
        "default_parameters": raw.get("default_parameters") or {},
        "raw_metadata": raw,
        "extra": {},
    }


def _remote_payload_models(payload: Any) -> Any:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return None
    return payload.get("data")


async def _fetch_remote_model_type(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    provider: ModelProvider,
    endpoint: str | None,
    model_type: str,
) -> list[dict[str, Any]]:
    if not endpoint:
        return []
    response = await client.get(_models_url(provider.base_url, endpoint), headers=headers)
    response.raise_for_status()
    payload = response.json()
    raw_models = _remote_payload_models(payload)
    if not isinstance(raw_models, list):
        raise ValueError("models endpoint response must be a list or an object with data list")
    return [
        _normalize_remote_model(item, model_type)
        for item in raw_models
        if isinstance(item, dict)
    ]


async def fetch_remote_models(provider: ModelProvider) -> list[dict[str, Any]]:
    headers = dict(provider.headers_json or {})
    api_key = resolve_api_key(provider)
    if api_key:
        headers.setdefault("Authorization", f"Bearer {api_key}")

    capabilities = set(provider.capabilities or [])
    endpoint_specs: list[tuple[str | None, str]] = [(provider.models_endpoint, "chat")]
    if "embedding" in capabilities:
        endpoint_specs.append((provider.embedding_models_endpoint, "embedding"))
    if "rerank" in capabilities:
        endpoint_specs.append((provider.rerank_models_endpoint, "rerank"))

    async with httpx.AsyncClient(timeout=40.0) as client:
        results = await asyncio.gather(
            *[
                _fetch_remote_model_type(client, headers, provider, endpoint, model_type)
                for endpoint, model_type in endpoint_specs
            ],
        )
    seen: set[tuple[str, str]] = set()
    models: list[dict[str, Any]] = []
    for group in results:
        for item in group:
            if not item:
                continue
            key = (item["id"], item["type"])
            if key not in seen:
                seen.add(key)
                models.append(item)
    return models


async def test_model_status_by_spec(spec: str) -> dict[str, Any]:
    from app.llm.factory import get_model_by_spec
    from app.llm.providers.cache import model_cache

    try:
        info = model_cache.get_model_info(spec)
        if info is None:
            raise ValueError(f"Unknown model spec: {spec}")
        if info.provider_type == "mock":
            return {"spec": spec, "status": "available", "message": "mock model is available", "model_type": info.model_type}
        if info.model_type == "embedding":
            return await _test_embedding_model(info)
        if info.model_type == "rerank":
            return await _test_rerank_model(info)

        model = get_model_by_spec(spec)
        response = await model.ainvoke("Say 1")
        if response.content:
            return {"spec": spec, "status": "available", "message": "connection ok", "model_type": "chat"}
        return {"spec": spec, "status": "unavailable", "message": "empty response", "model_type": "chat"}
    except Exception as error:
        return {"spec": spec, "status": "error", "message": str(error)}


async def _test_embedding_model(info: Any) -> dict[str, Any]:
    if not info.api_key:
        raise ValueError("Embedding API key is required.")
    payload = {"model": info.model_id, "input": ["miniBOT connectivity test"]}
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            _url_with_endpoint(info.base_url, "embeddings"),
            headers={
                "Authorization": f"Bearer {info.api_key}",
                "Content-Type": "application/json",
                **dict(info.headers or {}),
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()
    embeddings = data.get("data") if isinstance(data, dict) else None
    if isinstance(embeddings, list) and embeddings:
        return {
            "spec": info.spec,
            "status": "available",
            "message": "embedding connection ok",
            "model_type": "embedding",
        }
    return {"spec": info.spec, "status": "unavailable", "message": "empty embedding response", "model_type": "embedding"}


async def _test_rerank_model(info: Any) -> dict[str, Any]:
    if not info.api_key:
        raise ValueError("Rerank API key is required.")
    payload = {
        "model": info.model_id,
        "query": "miniBOT connectivity test",
        "documents": ["miniBOT is testing rerank connectivity.", "Unrelated document."],
        "top_n": 2,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            info.base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {info.api_key}",
                "Content-Type": "application/json",
                **dict(info.headers or {}),
            },
            json=payload,
        )
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            body = response.text[:1000]
            raise ValueError(f"Rerank request failed: status={response.status_code}, body={body}") from error
        data = response.json()
    if isinstance(data, dict) and (data.get("results") or (data.get("output") or {}).get("results")):
        return {
            "spec": info.spec,
            "status": "available",
            "message": "rerank connection ok",
            "model_type": "rerank",
        }
    return {"spec": info.spec, "status": "unavailable", "message": "empty rerank response", "model_type": "rerank"}
