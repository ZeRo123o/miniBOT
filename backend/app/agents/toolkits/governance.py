import logging
from uuid import uuid4
from typing import Any

logger = logging.getLogger(__name__)
MAX_LOGGED_ERROR_CHARS = 500

_TOOL_ACTIVITY = {
    "task": ("委派子任务", "正在启动专业子任务", "子任务已返回结果"),
    "tavily_search": ("搜索公开资料", "正在检索相关网页", "已完成公开资料搜索"),
    "exchange_rate": ("查询参考汇率", "正在查询货币参考汇率", "已完成货币换算"),
    "query_kb": ("检索知识库", "正在检索已启用知识库", "已找到相关知识片段"),
    "list_kbs": ("查看知识库", "正在读取可用知识库", "已读取知识库列表"),
    "sandbox_read_file": ("阅读文件", "正在读取工作区文件", "已读取文件"),
    "sandbox_grep": ("搜索代码与文本", "正在定位相关内容", "已找到匹配内容"),
    "sandbox_glob": ("查找文件", "正在扫描文件路径", "已找到候选文件"),
    "sandbox_ls": ("查看目录", "正在读取目录内容", "已读取目录内容"),
    "sandbox_write_file": ("写入文件", "正在写入工作区文件", "已写入文件"),
    "present_artifacts": ("整理交付物", "正在登记交付文件", "已登记交付文件"),
    "install_skill": ("安装 Skill", "正在安装所需 Skill", "已安装 Skill"),
}


class _ToolEvent(dict):
    """Dictionary event that keeps its runtime-only SSE sink outside persisted metadata."""

    def __init__(self, context: Any, **payload: Any) -> None:
        super().__init__(payload)
        self.context = context


def context_value(context: Any, name: str, default: Any) -> Any:
    """兼容 dataclass 和 dict 两种 Agent runtime context。"""
    if isinstance(context, dict):
        return context.get(name, default)
    return getattr(context, name, default)


def start_tool_call(
    context: Any,
    *,
    tool_name: str,
    payload: dict[str, Any] | None = None,
    tool_call_id: str | None = None,
) -> dict[str, Any] | None:
    """创建可供日志、审计和 citation 使用的工具事件。"""
    tool_events = context_value(context, "tool_events", None)
    # This id is the stable UI key. `task` supplies its LangGraph call id so child
    # events can be rendered beneath the exact delegation call.
    event = _ToolEvent(
        context,
        id=tool_call_id or f"tool_{uuid4().hex}",
        tool_name=tool_name,
        status="started",
        **(payload or {}),
    )
    subagent_type = context_value(context, "subagent_type", "")
    if subagent_type:
        event["subagent_type"] = subagent_type
        event["child_thread_id"] = context_value(context, "thread_id", "")
        event["parent_tool_call_id"] = context_value(context, "parent_tool_call_id", "")
    logger.info(
        "Agent tool call started: tool=%s user_id=%s conversation_id=%s",
        tool_name,
        context_value(context, "user_id", ""),
        context_value(context, "conversation_id", None),
    )
    if isinstance(tool_events, list):
        tool_events.append(event)
    emit_runtime_event(context, {"type": "tool_event", "event": _streamable_tool_event(event)})
    return event


def finish_tool_call(event: dict[str, Any] | None, **metadata: Any) -> None:
    """把工具事件标记为成功，并附加结果元数据。"""
    if event is None:
        return
    event.update(metadata)
    event["status"] = "finished"
    logger.info(
        "Agent tool call finished: tool=%s",
        event.get("tool_name", ""),
    )
    emit_runtime_event(getattr(event, "context", None), {"type": "tool_event", "event": _streamable_tool_event(event)})


def fail_tool_call(event: dict[str, Any] | None, error: Any) -> None:
    """把工具事件标记为失败，并记录错误信息。"""
    if event is None:
        return
    event["status"] = "failed"
    event["error"] = str(error)
    logger.warning(
        "Agent tool call failed: tool=%s error_type=%s",
        event.get("tool_name", ""),
        type(error).__name__,
    )
    emit_runtime_event(getattr(event, "context", None), {"type": "tool_event", "event": _streamable_tool_event(event)})


def emit_runtime_event(context: Any, event: dict[str, Any]) -> None:
    """Send a lightweight, non-sensitive event to the active SSE stream when present."""
    sink = context_value(context, "runtime_event_sink", None)
    if callable(sink):
        # Queue consumers run later; copy nested dictionaries before the tool lifecycle mutates them.
        stream_event = dict(event)
        if isinstance(event.get("event"), dict):
            stream_event["event"] = dict(event["event"])
        sink(stream_event)


def _streamable_tool_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return the Yuxi-style tool-call shape used by the live chat renderer."""
    payload = {
        "id": str(event.get("id") or ""),
        "tool_name": str(event.get("tool_name") or ""),
        "status": str(event.get("status") or ""),
        "args": _display_args(event),
    }
    for key in (
        "subagent_type",
        "child_thread_id",
        "parent_tool_call_id",
        "truncated",
        "child_tool_event_count",
    ):
        if key in event:
            payload[key] = event[key]
    if event.get("status") == "failed":
        payload["error"] = str(event.get("error") or "")[:MAX_LOGGED_ERROR_CHARS]
    if isinstance(event.get("child_tool_calls"), list):
        payload["child_tool_calls"] = [
            _streamable_tool_event(child_event)
            for child_event in event["child_tool_calls"]
            if isinstance(child_event, dict)
        ]
    payload["activity"] = _activity_summary(event)
    return payload


def serialize_tool_calls(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Persist the same compact tool-call model rendered during SSE streaming."""
    return [_streamable_tool_event(event) for event in events]


def _display_args(event: dict[str, Any]) -> dict[str, Any]:
    """Keep only concise UI inputs; never expose file contents or credentials."""
    allowed = {
        "query",
        "description",
        "subagent_type",
        "kb_id",
        "path",
        "pattern",
        "glob",
        "filepaths",
        "skill_names",
        "from_currency",
        "to_currency",
        "amount",
    }
    result: dict[str, Any] = {}
    for key in allowed:
        value = event.get(key)
        if isinstance(value, str):
            result[key] = value[:200]
        elif isinstance(value, (int, float, bool)):
            result[key] = value
        elif key in {"filepaths", "skill_names"} and isinstance(value, list):
            result[key] = [str(item)[:120] for item in value[:10]]
    return result


def _activity_summary(event: dict[str, Any]) -> dict[str, str]:
    """Map a tool lifecycle event to a short, safe user-facing work summary."""
    tool_name = str(event.get("tool_name") or "")
    title, started, finished = _TOOL_ACTIVITY.get(
        tool_name,
        ("调用工具", "正在执行工具", "已完成工具调用"),
    )
    status = str(event.get("status") or "")
    if status == "started":
        detail = started
    elif status == "failed":
        detail = "执行失败，请查看错误信息"
    else:
        detail = finished
        if isinstance(event.get("result_count"), int):
            detail = f"{detail}（{event['result_count']} 项）"
        elif isinstance(event.get("artifacts"), list):
            detail = f"{detail}（{len(event['artifacts'])} 个文件）"
        elif isinstance(event.get("installed_skills"), list):
            detail = f"{detail}（{len(event['installed_skills'])} 项）"
    return {"title": title, "detail": detail}
