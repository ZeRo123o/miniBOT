from __future__ import annotations

import asyncio
import hashlib
from collections.abc import Awaitable, Callable
from dataclasses import replace as dataclass_replace
from typing import Any

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.types import Command

from app.agents.backends.filesystem import AgentFilesystemBackend, create_agent_filesystem_backend
from app.agents.backends.sandbox.paths import VIRTUAL_WORKSPACE_ROOT
from app.agents.buildin.chatbot.context import AgentContext

_OFFLOAD_DIR = ".minibot/tool_outputs"
_TOOL_RESULT_SAVED_MARKER = "minibot_tool_result_saved"
_TOOL_RESULT_BUDGETED_MARKER = "minibot_tool_output_budgeted"


def _message_text(content: Any) -> str | None:
    """Extract plain text from ToolMessage content and skip non-text blocks."""
    if isinstance(content, str):
        return content
    if content is None:
        return None
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            else:
                return None
        return "\n".join(parts) if parts else None
    return None


def _snap_to_line_boundary(text: str, position: int) -> int:
    if position <= 0 or position >= len(text):
        return position
    newline = text.rfind("\n", position // 2, position)
    return newline + 1 if newline >= 0 else position


def _safe_tool_name(name: str | None) -> str:
    value = str(name or "unknown").strip()
    safe = "".join(char if char.isalnum() or char in "-_." else "_" for char in value)
    return safe.strip("._-") or "tool-result"


def _offload_path(message: ToolMessage, content: str) -> str:
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()[:16]
    tool_name = _safe_tool_name(message.name)
    return f"{VIRTUAL_WORKSPACE_ROOT}/{_OFFLOAD_DIR}/{tool_name}-{digest}.txt"


def _build_file_content(message: ToolMessage, content: str) -> str:
    tool_name = message.name or "unknown"
    header = "\n".join(
        [
            "=== Tool Invocation ===",
            f"Tool: {tool_name}",
            f"Tool Call ID: {message.tool_call_id or ''}",
            "=" * 40,
            "",
        ]
    )
    return header + content


def _build_preview(
    content: str,
    *,
    tool_name: str,
    file_path: str,
    head_chars: int,
    tail_chars: int,
) -> str:
    total_chars = len(content)
    head_end = _snap_to_line_boundary(content, min(max(0, head_chars), total_chars))
    tail_start = max(head_end, total_chars - max(0, tail_chars))
    snapped_tail_start = _snap_to_line_boundary(content, tail_start)
    if snapped_tail_start > head_end:
        tail_start = snapped_tail_start

    head = content[:head_end]
    tail = content[tail_start:] if tail_start < total_chars else ""
    omitted_chars = max(0, total_chars - len(head) - len(tail))
    reference = (
        f"\n\n[ToolResultOffloaded]\n"
        f"Tool: {tool_name}\n"
        f"Full output path: {file_path}\n"
        f"Total chars: {total_chars}\n"
        "Use sandbox_read_file with start_line/end_line to inspect specific sections.\n"
        f"Preview omitted chars: {omitted_chars}\n"
        "[/ToolResultOffloaded]\n\n"
    )
    return "".join([head, reference, tail])


def _build_fallback(
    content: str,
    *,
    tool_name: str,
    max_chars: int,
    head_chars: int,
    tail_chars: int,
) -> str:
    if max_chars <= 0 or len(content) <= max_chars:
        return content

    marker_template = (
        "\n\n[Tool output truncated: {omitted} chars omitted from {tool_name}. "
        "Persistent storage was unavailable.]\n\n"
    )
    marker = marker_template.format(omitted=len(content), tool_name=tool_name)
    if len(marker) >= max_chars:
        return content[:max_chars]

    budget = max_chars - len(marker)
    effective_head = min(max(0, head_chars), budget)
    effective_tail = min(max(0, tail_chars), max(0, budget - effective_head))
    head_end = _snap_to_line_boundary(content, min(effective_head, len(content)))
    tail_start = max(head_end, len(content) - effective_tail)
    snapped_tail_start = _snap_to_line_boundary(content, tail_start)
    if snapped_tail_start > head_end:
        tail_start = snapped_tail_start

    head = content[:head_end]
    tail = content[tail_start:] if tail_start < len(content) else ""
    omitted = max(0, len(content) - len(head) - len(tail))
    return "".join(
        [
            head,
            marker_template.format(omitted=omitted, tool_name=tool_name),
            tail,
        ]
    )


def _context(request: ToolCallRequest | ModelRequest) -> AgentContext | None:
    runtime = getattr(request, "runtime", None)
    context = getattr(runtime, "context", None)
    return context if isinstance(context, AgentContext) else None


def _backend(request: ToolCallRequest | ModelRequest) -> AgentFilesystemBackend | None:
    runtime = getattr(request, "runtime", None)
    return create_agent_filesystem_backend(runtime) if runtime is not None else None


def _is_saved(message: ToolMessage) -> bool:
    kwargs = getattr(message, "additional_kwargs", {}) or {}
    return kwargs.get(_TOOL_RESULT_SAVED_MARKER) is True or kwargs.get(_TOOL_RESULT_BUDGETED_MARKER) is True


def _budget_trigger(context: AgentContext) -> int:
    return int(context.tool_output_offload_threshold_chars)


def _over_budget(message: ToolMessage, context: AgentContext) -> bool:
    if _is_saved(message):
        return False
    threshold = _budget_trigger(context)
    if threshold <= 0:
        return False
    content = _message_text(message.content)
    return content is not None and len(content) > threshold


def _needs_budget(result: ToolMessage | Command, context: AgentContext) -> bool:
    if isinstance(result, ToolMessage):
        return _over_budget(result, context)
    update = getattr(result, "update", None)
    if not isinstance(update, dict):
        return False
    messages = update.get("messages")
    if not isinstance(messages, list):
        return False
    return any(isinstance(message, ToolMessage) and _over_budget(message, context) for message in messages)


def _patch_tool_message(
    message: ToolMessage,
    *,
    context: AgentContext,
    backend: AgentFilesystemBackend | None,
) -> ToolMessage:
    content = _message_text(message.content)
    if content is None or not _over_budget(message, context):
        return message

    tool_name = message.name or "unknown"
    replacement: str | None = None
    file_path = _offload_path(message, content)
    if backend is not None:
        write_result = backend.write(file_path, _build_file_content(message, content))
        if not write_result.error:
            replacement = _build_preview(
                content,
                tool_name=tool_name,
                file_path=file_path,
                head_chars=context.tool_output_preview_head_chars,
                tail_chars=context.tool_output_preview_tail_chars,
            )

    if replacement is None:
        replacement = _build_fallback(
            content,
            tool_name=tool_name,
            max_chars=context.tool_output_fallback_max_chars,
            head_chars=context.tool_output_preview_head_chars,
            tail_chars=context.tool_output_preview_tail_chars,
        )
        if replacement == content:
            return message

    additional_kwargs = dict(getattr(message, "additional_kwargs", {}) or {})
    additional_kwargs[_TOOL_RESULT_SAVED_MARKER] = replacement.startswith("\n\n[ToolResultOffloaded]") or "[ToolResultOffloaded]" in replacement
    additional_kwargs[_TOOL_RESULT_BUDGETED_MARKER] = True
    return message.model_copy(
        update={
            "content": replacement,
            "additional_kwargs": additional_kwargs,
        }
    )


def _patch_result(
    result: ToolMessage | Command,
    *,
    context: AgentContext,
    backend: AgentFilesystemBackend | None,
) -> ToolMessage | Command:
    if isinstance(result, ToolMessage):
        return _patch_tool_message(result, context=context, backend=backend)

    update = getattr(result, "update", None)
    if not isinstance(update, dict):
        return result
    messages = update.get("messages")
    if not isinstance(messages, list):
        return result

    changed = False
    patched_messages: list[Any] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            patched = _patch_tool_message(message, context=context, backend=backend)
            changed = changed or patched is not message
            patched_messages.append(patched)
        else:
            patched_messages.append(message)
    if not changed:
        return result
    return dataclass_replace(result, update={**update, "messages": patched_messages})


async def _apatch_result(
    result: ToolMessage | Command,
    *,
    context: AgentContext,
    backend: AgentFilesystemBackend | None,
) -> ToolMessage | Command:
    return await asyncio.to_thread(
        _patch_result,
        result,
        context=context,
        backend=backend,
    )


def _patch_historical_messages(
    messages: list[Any],
    *,
    context: AgentContext,
    backend: AgentFilesystemBackend | None,
) -> list[Any] | None:
    if not any(isinstance(message, ToolMessage) and _over_budget(message, context) for message in messages):
        return None

    changed = False
    patched_messages: list[Any] = []
    for message in messages:
        if isinstance(message, ToolMessage):
            patched = _patch_tool_message(message, context=context, backend=backend)
            changed = changed or patched is not message
            patched_messages.append(patched)
        else:
            patched_messages.append(message)
    return patched_messages if changed else None


class ToolOutputBudgetMiddleware(AgentMiddleware):
    """Keep ToolMessage payloads bounded before they reach model context."""

    def wrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], ToolMessage | Command],
    ) -> ToolMessage | Command:
        result = handler(request)
        context = _context(request)
        if context is None or not context.tool_output_budget_enabled:
            return result
        if not _needs_budget(result, context):
            return result
        return _patch_result(result, context=context, backend=_backend(request))

    async def awrap_tool_call(
        self,
        request: ToolCallRequest,
        handler: Callable[[ToolCallRequest], Awaitable[ToolMessage | Command]],
    ) -> ToolMessage | Command:
        result = await handler(request)
        context = _context(request)
        if context is None or not context.tool_output_budget_enabled:
            return result
        if not _needs_budget(result, context):
            return result
        return await _apatch_result(result, context=context, backend=_backend(request))

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse:
        context = _context(request)
        messages = getattr(request, "messages", None)
        if context is not None and context.tool_output_budget_enabled and isinstance(messages, list):
            patched = _patch_historical_messages(messages, context=context, backend=_backend(request))
            if patched is not None:
                request = request.override(messages=patched)
        return handler(request)

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse:
        context = _context(request)
        messages = getattr(request, "messages", None)
        if context is not None and context.tool_output_budget_enabled and isinstance(messages, list):
            backend = _backend(request)
            patched = await asyncio.to_thread(
                _patch_historical_messages,
                messages,
                context=context,
                backend=backend,
            )
            if patched is not None:
                request = request.override(messages=patched)
        return await handler(request)
