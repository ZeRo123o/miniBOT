from __future__ import annotations

import json
import logging
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from app.core.config import get_settings
from app.storage.redis import sync_redis_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ModelInfo:
    provider_id: str
    model_id: str
    model_type: str
    display_name: str
    api_key: str
    base_url: str
    provider_type: str
    headers: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    dimension: int | None = None
    batch_size: int = 40

    @property
    def spec(self) -> str:
        return f"{self.provider_id}:{self.model_id}"

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelInfo":
        return cls(
            provider_id=data["provider_id"],
            model_id=data["model_id"],
            model_type=data["model_type"],
            display_name=data["display_name"],
            api_key=data.get("api_key") or "",
            base_url=data["base_url"],
            provider_type=data["provider_type"],
            headers=dict(data.get("headers") or {}),
            extra=dict(data.get("extra") or {}),
            dimension=data.get("dimension"),
            batch_size=int(data.get("batch_size") or 40),
        )


@dataclass(frozen=True)
class ModelCacheSnapshot:
    models: dict[str, ModelInfo]
    model_uses: dict[str, str]


class ModelRuntimeCache:
    """Redis-backed runtime cache for model specs and model-use mappings."""

    def __init__(self) -> None:
        self._local_snapshot: ModelCacheSnapshot | None = None
        self._local_cache_at = 0.0

    def rebuild(self, providers: list[Any], model_use_configs: list[Any] | None = None) -> None:
        from app.llm.providers.service import resolve_api_key
        from app.knowledge.embedding.openai import resolve_embedding_batch_size

        models: dict[str, ModelInfo] = {}
        for provider in providers:
            if not provider.is_enabled or provider.provider_type == "mock":
                continue
            api_key = resolve_api_key(provider) or ""
            for model in provider.enabled_models or []:
                model_id = str(model.get("id") or "").strip()
                if not model_id:
                    continue
                model_type = str(model.get("type") or "chat").strip()
                base_url = model.get("base_url_override") or self._base_url_for_type(provider, model_type)
                extra = {
                    **dict(provider.extra_json or {}),
                    **dict(model.get("extra") or {}),
                }
                self._apply_builtin_model_defaults(provider.provider_id, model_id, model_type, extra)
                info = ModelInfo(
                    provider_id=provider.provider_id,
                    model_id=model_id,
                    model_type=model_type,
                    display_name=str(model.get("display_name") or model_id),
                    api_key=api_key,
                    base_url=base_url,
                    provider_type=provider.provider_type,
                    headers=dict(provider.headers_json or {}),
                    extra=extra,
                    dimension=model.get("dimension"),
                    batch_size=(
                        resolve_embedding_batch_size(
                            provider_id=provider.provider_id,
                            model_name=model_id,
                            base_url=base_url,
                            configured_batch_size=int(model.get("batch_size") or 40),
                        )
                        if model_type == "embedding"
                        else int(model.get("batch_size") or 40)
                    ),
                )
                models[info.spec] = info

        model_uses = {
            item.model_use: item.model_spec
            for item in (model_use_configs or [])
            if item.model_use and item.model_spec in models
        }
        snapshot = ModelCacheSnapshot(models=models, model_uses=model_uses)
        self._save_snapshot(snapshot)
        self._set_local_snapshot(snapshot)

    def get_model_info(self, spec: str) -> ModelInfo | None:
        return self._load_snapshot().models.get(spec)

    def get_all_specs(self, model_type: str | None = None) -> list[ModelInfo]:
        models = list(self._load_snapshot().models.values())
        if model_type is None:
            return models
        return [item for item in models if item.model_type == model_type]

    def get_specs_grouped_by_provider(self, model_type: str = "chat") -> dict[str, list[ModelInfo]]:
        grouped: dict[str, list[ModelInfo]] = {}
        for item in self.get_all_specs(model_type):
            grouped.setdefault(item.provider_id, []).append(item)
        return grouped

    def get_model_use_spec(self, model_use: str) -> str | None:
        return self._load_snapshot().model_uses.get(model_use)

    def _load_snapshot(self) -> ModelCacheSnapshot:
        now = time.monotonic()
        ttl = get_settings().model_cache_local_ttl_seconds
        if self._local_snapshot is not None and now - self._local_cache_at < ttl:
            return self._local_snapshot

        try:
            with sync_redis_client() as redis_client:
                raw = redis_client.get(get_settings().model_cache_redis_key)
            if raw:
                snapshot = self._snapshot_from_json(raw)
                self._set_local_snapshot(snapshot)
                return snapshot
        except Exception as exc:
            logger.warning("Failed to load model runtime cache from Redis: %s", exc)

        return self._local_snapshot or ModelCacheSnapshot(models={}, model_uses={})

    def _save_snapshot(self, snapshot: ModelCacheSnapshot) -> None:
        try:
            with sync_redis_client() as redis_client:
                redis_client.set(get_settings().model_cache_redis_key, self._snapshot_to_json(snapshot))
        except Exception as exc:
            logger.warning("Failed to save model runtime cache to Redis; using local cache only: %s", exc)

    def _set_local_snapshot(self, snapshot: ModelCacheSnapshot) -> None:
        self._local_snapshot = snapshot
        self._local_cache_at = time.monotonic()

    @staticmethod
    def _snapshot_to_json(snapshot: ModelCacheSnapshot) -> str:
        payload = {
            "version": 1,
            "rebuilt_at": time.time(),
            "models": {spec: asdict(info) for spec, info in snapshot.models.items()},
            "model_uses": snapshot.model_uses,
        }
        return json.dumps(payload, ensure_ascii=False)

    @staticmethod
    def _snapshot_from_json(raw: str) -> ModelCacheSnapshot:
        payload = json.loads(raw)
        models = {
            spec: ModelInfo.from_dict(data)
            for spec, data in (payload.get("models") or {}).items()
            if isinstance(data, dict)
        }
        model_uses = {
            str(model_use): str(model_spec)
            for model_use, model_spec in (payload.get("model_uses") or {}).items()
            if model_use and model_spec
        }
        return ModelCacheSnapshot(models=models, model_uses=model_uses)

    @staticmethod
    def _base_url_for_type(provider: Any, model_type: str) -> str:
        if model_type == "embedding" and provider.embedding_base_url:
            return provider.embedding_base_url
        if model_type == "rerank" and provider.rerank_base_url:
            return provider.rerank_base_url
        return provider.base_url

    @staticmethod
    def _apply_builtin_model_defaults(provider_id: str, model_id: str, model_type: str, extra: dict[str, Any]) -> None:
        if model_type == "rerank" and provider_id == "alibaba" and model_id == "qwen3-rerank":
            extra.setdefault("rerank_protocol", "dashscope_compatible")


model_cache = ModelRuntimeCache()


def resolve_model_spec(spec: str) -> ModelInfo:
    if not spec:
        raise ValueError("model spec cannot be empty")
    info = model_cache.get_model_info(spec)
    if info:
        return info
    available = [item.spec for item in model_cache.get_all_specs()[:10]]
    raise ValueError(f"Unknown model spec '{spec}'. Available models: {available}")
