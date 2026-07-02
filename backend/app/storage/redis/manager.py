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


@contextmanager
def sync_redis_client(*, ping: bool = False) -> Iterator[Any]:
    client = create_sync_redis_client(ping=ping)
    try:
        yield client
    finally:
        client.close()
