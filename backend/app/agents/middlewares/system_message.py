from typing import Any

from langchain_core.messages import SystemMessage


def append_system_message(message: SystemMessage | None, section: str) -> SystemMessage:
    """向 system message 追加独立文本块，并避免同一段被重复注入。"""
    normalized = section.strip()
    if not normalized:
        return message or SystemMessage(content="")

    existing_text = _message_text(message)
    if normalized in existing_text:
        return message or SystemMessage(content=normalized)

    existing_blocks = list(message.content_blocks) if message else []
    return SystemMessage(content=[*existing_blocks, {"type": "text", "text": normalized}])


def _message_text(message: Any) -> str:
    """提取 system message 的文本内容，用于增量注入去重。"""
    if message is None:
        return ""
    content = getattr(message, "content", "")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(block.get("text", ""))
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        )
    return str(content)
