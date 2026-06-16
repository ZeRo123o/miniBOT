from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from langgraph.runtime import Runtime

from app.agents.buildin.chatbot.context import AgentContext
from app.agents.backends.sandbox.paths import resolve_host_path


@dataclass(slots=True)
class BackendWriteResult:
    path: str
    error: str | None = None
    files_update: dict[str, Any] = field(default_factory=dict)


class AgentFilesystemBackend:
    """Write virtual agent paths to the storage backing the current runtime."""

    def __init__(self, context: AgentContext):
        self._context = context

    def write(self, path: str, content: str) -> BackendWriteResult:
        if self._context.conversation_id is None:
            return BackendWriteResult(path=path, error="conversation_id is required")
        try:
            host_path = resolve_host_path(
                self._context.user_key,
                self._context.conversation_id,
                path,
                write=True,
            )
            host_path.parent.mkdir(parents=True, exist_ok=True)
            host_path.write_text(content, encoding="utf-8")
        except Exception as exc:
            return BackendWriteResult(path=path, error=str(exc))
        return BackendWriteResult(path=path, files_update={path: {"path": path}})

    async def awrite(self, path: str, content: str) -> BackendWriteResult:
        return await asyncio.to_thread(self.write, path, content)


def create_agent_filesystem_backend(runtime: Runtime) -> AgentFilesystemBackend | None:
    context = getattr(runtime, "context", None)
    if not isinstance(context, AgentContext):
        return None
    return AgentFilesystemBackend(context)
