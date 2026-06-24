from __future__ import annotations

import asyncio
from pathlib import PurePosixPath
from typing import Annotated, Any

from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import Field

from app.agents.backends.filesystem import create_agent_filesystem_backend
from app.agents.backends.sandbox.paths import (
    can_list,
    can_read,
    can_write,
    normalize_virtual_path,
)
from app.agents.backends.sandbox.provider import SandboxConnection, get_sandbox_provider
from app.agents.toolkits.governance import (
    fail_tool_call,
    finish_tool_call,
    start_tool_call,
)
from app.agents.toolkits.registry import tool
from app.core.config import get_settings


SandboxPath = Annotated[
    str,
    Field(description="沙盒绝对路径，例如 /mnt/user-data/workspace"),
]
SandboxContent = Annotated[
    str,
    Field(description="要写入文件的 UTF-8 文本内容"),
]
SandboxGlobPattern = Annotated[
    str,
    Field(description="相对于 path 的 glob，例如 **/*.py"),
]
SandboxSearchPattern = Annotated[
    str,
    Field(description="要搜索的文本或正则表达式"),
]


def _runtime_context(runtime: ToolRuntime | None) -> Any:
    return runtime.context if runtime is not None else None


def _readable_skill_slugs(context: Any) -> list[str]:
    """Return the Skill dependency closure prepared by SkillsMiddleware."""
    visible_skills = getattr(context, "_visible_skills", None)
    source = (
        visible_skills
        if isinstance(visible_skills, list)
        else getattr(context, "skills", [])
    )
    return list(
        dict.fromkeys(
            slug.strip()
            for slug in source or []
            if isinstance(slug, str) and slug.strip()
        )
    )


def _ensure_sandbox(runtime: ToolRuntime) -> SandboxConnection:
    """从运行时状态复用沙盒，缺失时按用户和会话延迟创建。"""
    context = _runtime_context(runtime)
    user_id = str(getattr(context, "user_id", "") or "").strip()
    conversation_id = getattr(context, "conversation_id", None)
    if not user_id or conversation_id is None:
        raise ValueError("sandbox requires user_id and conversation_id")

    state = runtime.state
    provider = get_sandbox_provider()

    # acquire() synchronizes the latest readable Skill closure before reusing
    # or creating the conversation-scoped sandbox.
    connection = provider.acquire(
        user_id=user_id,
        conversation_id=int(conversation_id),
        skills=_readable_skill_slugs(context),
    )
    if isinstance(state, dict):
        state["sandbox"] = {"sandbox_id": connection.sandbox_id}
    if context is not None:
        context.sandbox_id = connection.sandbox_id
    return connection


def _validate_path(path: str, *, operation: str) -> str:
    normalized = normalize_virtual_path(path)
    if operation == "write" and not can_write(normalized):
        raise PermissionError(
            "write is allowed only under /mnt/user-data/workspace or "
            "/mnt/user-data/outputs"
        )
    if operation == "read" and not can_read(normalized):
        raise PermissionError("path is outside readable sandbox roots")
    if operation == "list" and not can_list(normalized):
        raise PermissionError("path is outside listable sandbox roots")
    return normalized


def _filesystem_backend(runtime: ToolRuntime):
    backend = create_agent_filesystem_backend(runtime)
    if backend is None:
        raise ValueError("filesystem backend requires AgentContext runtime")
    return backend


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


@tool(
    category="sandbox",
    tags=["沙盒", "文件", "只读"],
    display_name="读取沙盒文件",
)
async def sandbox_read_file(path: SandboxPath, runtime: ToolRuntime) -> str:
    """读取 workspace、uploads、outputs 或 skills 中的 UTF-8 文本文件。"""
    context = _runtime_context(runtime)
    event = start_tool_call(context, tool_name="sandbox_read_file", payload={"path": path})
    try:
        normalized = _validate_path(path, operation="read")
        backend = _filesystem_backend(runtime)
        result = await backend.aread(normalized)
        if result.error:
            raise ValueError(result.error)
        output, truncated = _truncate(result.content, get_settings().sandbox_max_output_bytes)
        finish_tool_call(
            event,
            virtual_path=normalized,
            truncated=truncated,
        )
        return output or "(empty)"
    except Exception as exc:  # noqa: BLE001
        fail_tool_call(event, exc)
        return f"Error: {exc}"


@tool(
    category="sandbox",
    tags=["沙盒", "文件", "写入"],
    display_name="写入沙盒文件",
)
async def sandbox_write_file(
    path: SandboxPath,
    content: SandboxContent,
    runtime: ToolRuntime,
) -> str:
    """将文本写入 workspace 或 outputs，已存在文件会被覆盖。"""
    context = _runtime_context(runtime)
    content_bytes = len(content.encode("utf-8"))
    event = start_tool_call(
        context,
        tool_name="sandbox_write_file",
        payload={"path": path, "content_bytes": content_bytes},
    )
    try:
        normalized = _validate_path(path, operation="write")
        max_bytes = get_settings().sandbox_max_write_bytes
        if content_bytes > max_bytes:
            raise ValueError(f"content exceeds sandbox write limit of {max_bytes} bytes")
        backend = _filesystem_backend(runtime)
        result = await backend.awrite(normalized, content)
        if result.error:
            raise ValueError(result.error)
        finish_tool_call(
            event,
            virtual_path=normalized,
            content_bytes=content_bytes,
        )
        return f"OK: {normalized}"
    except Exception as exc:  # noqa: BLE001
        fail_tool_call(event, exc)
        return f"Error: {exc}"


@tool(
    category="sandbox",
    tags=["沙盒", "文件", "目录"],
    display_name="列出沙盒目录",
)
async def sandbox_ls(path: SandboxPath, runtime: ToolRuntime) -> str:
    """列出受控沙盒目录的直接子项。"""
    context = _runtime_context(runtime)
    event = start_tool_call(context, tool_name="sandbox_ls", payload={"path": path})
    try:
        normalized = _validate_path(path, operation="list")
        backend = _filesystem_backend(runtime)
        result = await backend.als(normalized)
        if result.error:
            raise ValueError(result.error)
        lines = []
        for entry in result.entries[:200]:
            suffix = "/" if entry["is_dir"] else ""
            size = (
                f" ({entry['size']} bytes)"
                if entry.get("size") is not None and not entry["is_dir"]
                else ""
            )
            lines.append(f"{entry['path']}{suffix}{size}")
        finish_tool_call(
            event,
            virtual_path=normalized,
            result_count=len(lines),
        )
        return "\n".join(lines) or "(empty)"
    except Exception as exc:  # noqa: BLE001
        fail_tool_call(event, exc)
        return f"Error: {exc}"


@tool(
    category="sandbox",
    tags=["沙盒", "文件", "搜索"],
    display_name="匹配沙盒文件",
)
async def sandbox_glob(
    path: SandboxPath,
    pattern: SandboxGlobPattern,
    runtime: ToolRuntime,
) -> str:
    """在受控目录下按 glob 查找文件。"""
    context = _runtime_context(runtime)
    event = start_tool_call(
        context,
        tool_name="sandbox_glob",
        payload={"path": path, "pattern": pattern},
    )
    try:
        normalized = _validate_path(path, operation="read")
        if ".." in PurePosixPath(pattern).parts:
            raise ValueError("glob traversal is not allowed")
        backend = _filesystem_backend(runtime)
        result = await backend.aglob(normalized, pattern)
        if result.error:
            raise ValueError(result.error)
        matches = result.matches[:200]
        finish_tool_call(
            event,
            virtual_path=normalized,
            result_count=len(matches),
        )
        return "\n".join(matches) or "(no matches)"
    except Exception as exc:  # noqa: BLE001
        fail_tool_call(event, exc)
        return f"Error: {exc}"


@tool(
    category="sandbox",
    tags=["沙盒", "文件", "搜索"],
    display_name="搜索沙盒文件内容",
)
async def sandbox_grep(
    path: SandboxPath,
    pattern: SandboxSearchPattern,
    runtime: ToolRuntime,
    glob: Annotated[str, Field(description="候选文件 glob")] = "**/*",
    literal: Annotated[bool, Field(description="是否按普通文本匹配")] = True,
) -> str:
    """搜索受控目录中的文本文件，最多返回 100 行匹配。"""
    context = _runtime_context(runtime)
    event = start_tool_call(
        context,
        tool_name="sandbox_grep",
        payload={"path": path, "pattern": pattern, "glob": glob},
    )
    try:
        normalized = _validate_path(path, operation="read")
        if ".." in PurePosixPath(glob).parts:
            raise ValueError("glob traversal is not allowed")
        backend = _filesystem_backend(runtime)
        result = await backend.agrep(
            normalized,
            pattern,
            glob=glob,
            literal=literal,
            limit=100,
        )
        if result.error:
            raise ValueError(result.error)
        matches = result.matches

        output, truncated = _truncate(
            "\n".join(matches) or "(no matches)",
            get_settings().sandbox_max_output_bytes,
        )
        finish_tool_call(
            event,
            virtual_path=normalized,
            result_count=len(matches),
            truncated=truncated,
        )
        return output
    except Exception as exc:  # noqa: BLE001
        fail_tool_call(event, exc)
        return f"Error: {exc}"
