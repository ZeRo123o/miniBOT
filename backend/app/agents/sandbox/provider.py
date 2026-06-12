from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass

from app.agents.sandbox.client import AgentSandbox, ProvisionerClient
from app.agents.sandbox.paths import (
    ensure_scope_dirs,
    safe_user_segment,
    sandbox_id_for_scope,
    sync_readable_skills,
)
from app.core.config import get_settings

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class SandboxConnection:
    sandbox_id: str
    user_key: str
    conversation_id: int
    sandbox_url: str
    sandbox: AgentSandbox


class ProvisionerSandboxProvider:
    """按用户和会话获取、缓存并保活远程容器沙盒。"""

    def __init__(self) -> None:
        settings = get_settings()
        self._settings = settings
        self._client = ProvisionerClient(
            settings.sandbox_provisioner_url,
            settings.sandbox_internal_token,
        )
        self._lock = threading.Lock()
        self._scope_locks: dict[str, threading.Lock] = {}
        self._connections: dict[str, SandboxConnection] = {}
        self._last_touch_at: dict[str, float] = {}

    def _scope_lock(self, sandbox_id: str) -> threading.Lock:
        with self._lock:
            return self._scope_locks.setdefault(sandbox_id, threading.Lock())

    def acquire(
        self,
        *,
        user_key: str,
        conversation_id: int,
        skills: list[dict] | None = None,
    ) -> SandboxConnection:
        if not self._settings.sandbox_enabled:
            raise RuntimeError("sandbox is disabled")

        ensure_scope_dirs(user_key, conversation_id)
        sync_readable_skills(user_key, conversation_id, skills or [])
        sandbox_id = sandbox_id_for_scope(user_key, conversation_id)

        with self._scope_lock(sandbox_id):
            current = self._connections.get(sandbox_id)
            if current is not None:
                if self._should_touch(sandbox_id):
                    if not self._client.touch(sandbox_id):
                        self._connections.pop(sandbox_id, None)
                    else:
                        self._last_touch_at[sandbox_id] = time.time()
                        return current
                else:
                    return current

            record = self._client.create(
                sandbox_id=sandbox_id,
                user_segment=safe_user_segment(user_key),
                conversation_id=conversation_id,
            )
            connection = SandboxConnection(
                sandbox_id=sandbox_id,
                user_key=user_key,
                conversation_id=conversation_id,
                sandbox_url=record.sandbox_url,
                sandbox=AgentSandbox(
                    sandbox_id,
                    record.sandbox_url,
                    self._settings.sandbox_exec_timeout_seconds,
                ),
            )
            self._connections[sandbox_id] = connection
            self._last_touch_at[sandbox_id] = time.time()
            return connection

    def get(self, sandbox_id: str) -> SandboxConnection | None:
        return self._connections.get(sandbox_id)

    def _should_touch(self, sandbox_id: str) -> bool:
        last_touch = self._last_touch_at.get(sandbox_id)
        if last_touch is None:
            return True
        return (
            time.time() - last_touch
            >= self._settings.sandbox_keepalive_interval_seconds
        )

    def shutdown(self) -> None:
        with self._lock:
            sandbox_ids = list(self._connections)
            self._connections.clear()
            self._last_touch_at.clear()
        for sandbox_id in sandbox_ids:
            try:
                self._client.delete(sandbox_id)
            except Exception as exc:  # noqa: BLE001
                logger.warning("Failed to delete sandbox %s: %s", sandbox_id, exc)


_provider: ProvisionerSandboxProvider | None = None
_provider_lock = threading.Lock()


def get_sandbox_provider() -> ProvisionerSandboxProvider:
    global _provider
    with _provider_lock:
        if _provider is None:
            _provider = ProvisionerSandboxProvider()
        return _provider


def shutdown_sandbox_provider() -> None:
    global _provider
    with _provider_lock:
        provider = _provider
        _provider = None
    if provider is not None:
        provider.shutdown()
