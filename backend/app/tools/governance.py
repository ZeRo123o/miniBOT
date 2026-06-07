from typing import Any


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
) -> tuple[dict[str, Any] | None, str | None]:
    """统一检查调用上限，并创建可供日志和 citation 使用的工具事件。"""
    tool_events = context_value(context, "tool_events", None)
    max_tool_calls = int(context_value(context, "max_tool_calls", 3) or 3)
    if isinstance(tool_events, list) and len(tool_events) >= max_tool_calls:
        return None, f"工具调用次数已达到上限 {max_tool_calls}，本轮不再继续调用工具。"

    active_tool_names = context_value(context, "active_tool_names", None)
    if isinstance(active_tool_names, list):
        active_tool_names.append(tool_name)

    event = {"tool_name": tool_name, "status": "started", **(payload or {})}
    if isinstance(tool_events, list):
        tool_events.append(event)
    return event, None


def finish_tool_call(event: dict[str, Any] | None, **metadata: Any) -> None:
    """把工具事件标记为成功，并附加结果元数据。"""
    if event is None:
        return
    event.update(metadata)
    event["status"] = "finished"


def fail_tool_call(event: dict[str, Any] | None, error: Any) -> None:
    """把工具事件标记为失败，并记录错误信息。"""
    if event is None:
        return
    event["status"] = "failed"
    event["error"] = str(error)
