import logging
from typing import Any

logger = logging.getLogger(__name__)


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
) -> dict[str, Any] | None:
    """创建可供日志、审计和 citation 使用的工具事件。"""
    tool_events = context_value(context, "tool_events", None)
    event = {"tool_name": tool_name, "status": "started", **(payload or {})}
    logger.info(
        "Agent tool call started: tool=%s user_key=%s conversation_id=%s",
        tool_name,
        context_value(context, "user_key", ""),
        context_value(context, "conversation_id", None),
    )
    if isinstance(tool_events, list):
        tool_events.append(event)
        return event
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
