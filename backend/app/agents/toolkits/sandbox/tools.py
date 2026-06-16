from __future__ import annotations

import asyncio
import re
from pathlib import PurePosixPath
from typing import Annotated, Any

from langgraph.prebuilt.tool_node import ToolRuntime
from pydantic import Field

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
    user_key = str(getattr(context, "user_key", "") or "").strip()
    conversation_id = getattr(context, "conversation_id", None)
    if not user_key or conversation_id is None:
        raise ValueError("sandbox requires user_key and conversation_id")

    state = runtime.state
    provider = get_sandbox_provider()

    # acquire() synchronizes the latest readable Skill closure before reusing
    # or creating the conversation-scoped sandbox.
    connection = provider.acquire(
        user_key=user_key,
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


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text, False
    return encoded[:limit].decode("utf-8", errors="ignore"), True


@tool(
    category="buildin",
    tags=["沙盒", "文件", "只读"],
    display_name="读取沙盒文件",
)
async def sandbox_read_file(path: SandboxPath, runtime: ToolRuntime) -> str:
    """读取 workspace、uploads、outputs 或 skills 中的 UTF-8 文本文件。"""
    context = _runtime_context(runtime)
    event = start_tool_call(context, tool_name="sandbox_read_file", payload={"path": path})
    try:
        normalized = _validate_path(path, operation="read")
        connection = await asyncio.to_thread(_ensure_sandbox, runtime)
        content = await asyncio.to_thread(connection.sandbox.read_text, normalized)
        output, truncated = _truncate(content, get_settings().sandbox_max_output_bytes)
        finish_tool_call(
            event,
            sandbox_id=connection.sandbox_id,
            virtual_path=normalized,
            truncated=truncated,
        )
        return output or "(empty)"
    except Exception as exc:  # noqa: BLE001
        fail_tool_call(event, exc)
        return f"Error: {exc}"


@tool(
    category="buildin",
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
        connection = await asyncio.to_thread(_ensure_sandbox, runtime)
        await asyncio.to_thread(connection.sandbox.write_text, normalized, content)
        finish_tool_call(
            event,
            sandbox_id=connection.sandbox_id,
            virtual_path=normalized,
            content_bytes=content_bytes,
        )
        return f"OK: {normalized}"
    except Exception as exc:  # noqa: BLE001
        fail_tool_call(event, exc)
        return f"Error: {exc}"


@tool(
    category="buildin",
    tags=["沙盒", "文件", "目录"],
    display_name="列出沙盒目录",
)
async def sandbox_ls(path: SandboxPath, runtime: ToolRuntime) -> str:
    """列出受控沙盒目录的直接子项。"""
    context = _runtime_context(runtime)
    event = start_tool_call(context, tool_name="sandbox_ls", payload={"path": path})
    try:
        normalized = _validate_path(path, operation="list")
        connection = await asyncio.to_thread(_ensure_sandbox, runtime)
        entries = await asyncio.to_thread(connection.sandbox.list_path, normalized)
        lines = []
        for entry in entries[:200]:
            suffix = "/" if entry["is_dir"] else ""
            size = (
                f" ({entry['size']} bytes)"
                if entry.get("size") is not None and not entry["is_dir"]
                else ""
            )
            lines.append(f"{entry['path']}{suffix}{size}")
        finish_tool_call(
            event,
            sandbox_id=connection.sandbox_id,
            virtual_path=normalized,
            result_count=len(lines),
        )
        return "\n".join(lines) or "(empty)"
    except Exception as exc:  # noqa: BLE001
        fail_tool_call(event, exc)
        return f"Error: {exc}"


@tool(
    category="buildin",
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
        connection = await asyncio.to_thread(_ensure_sandbox, runtime)
        matches = await asyncio.to_thread(
            connection.sandbox.find_files,
            normalized,
            pattern,
        )
        matches = matches[:200]
        finish_tool_call(
            event,
            sandbox_id=connection.sandbox_id,
            virtual_path=normalized,
            result_count=len(matches),
        )
        return "\n".join(matches) or "(no matches)"
    except Exception as exc:  # noqa: BLE001
        fail_tool_call(event, exc)
        return f"Error: {exc}"


@tool(
    category="buildin",
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
        matcher = None if literal else re.compile(pattern, flags=re.IGNORECASE)
        connection = await asyncio.to_thread(_ensure_sandbox, runtime)
        files = await asyncio.to_thread(
            connection.sandbox.find_files,
            normalized,
            glob,
        )
        matches: list[str] = []
        for file_path in files[:200]:
            try:
                content = await asyncio.to_thread(connection.sandbox.read_text, file_path)
            except Exception:  # noqa: BLE001
                continue
            for line_number, line in enumerate(content.splitlines(), start=1):
                found = (
                    pattern.lower() in line.lower()
                    if literal
                    else bool(matcher and matcher.search(line))
                )
                if found:
                    matches.append(f"{file_path}:{line_number}: {line}")
                    if len(matches) >= 100:
                        break
            if len(matches) >= 100:
                break

        output, truncated = _truncate(
            "\n".join(matches) or "(no matches)",
            get_settings().sandbox_max_output_bytes,
        )
        finish_tool_call(
            event,
            sandbox_id=connection.sandbox_id,
            virtual_path=normalized,
            result_count=len(matches),
            truncated=truncated,
        )
        return output
    except Exception as exc:  # noqa: BLE001
        fail_tool_call(event, exc)
        return f"Error: {exc}"
