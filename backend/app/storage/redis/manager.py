from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from app.core.config import get_settings


def _redis_kwargs() -> dict[str, Any]:
    settings = get_settings()
    timeout = settings.redis_socket_timeout_seconds
    return {
        "decode_responses": True,
        "socket_connect_timeout": timeout,
        "socket_timeout": timeout,
    }


def create_sync_redis_client(*, ping: bool = False) -> Any:
    """Create one short-lived sync Redis client for cache reads/writes."""

    try:
        import redis
    except ImportError as exc:
        raise RuntimeError("redis dependency is required for Redis storage") from exc

    settings = get_settings()
    client = redis.from_url(settings.redis_url, **_redis_kwargs())
    if ping:
        client.ping()
    return client


async def create_async_redis_client(*, ping: bool = False, socket_timeout: float | None = None) -> Any:
    """Create an asyncio Redis client for long-lived streams and background runs."""
    try:
        import redis.asyncio as redis_async
    except ImportError as exc:
        raise RuntimeError("redis dependency is required for Redis storage") from exc

    settings = get_settings()
    kwargs = _redis_kwargs()
    if socket_timeout is not None:
        kwargs["socket_timeout"] = socket_timeout
    client = redis_async.from_url(settings.redis_url, **kwargs)
    if ping:
        await client.ping()
    return client


@contextmanager
def sync_redis_client(*, ping: bool = False) -> Iterator[Any]:
    client = create_sync_redis_client(ping=ping)
    try:
        yield client
    finally:
        client.close()
