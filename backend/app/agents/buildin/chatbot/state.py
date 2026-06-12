from typing import Annotated, NotRequired

from langchain.agents import AgentState


def merge_activated_skills(left: list[str] | None, right: list[str] | None) -> list[str]:
    """Merge activated Skill slugs without losing activation order."""
    result: list[str] = []
    seen: set[str] = set()
    for values in (left or [], right or []):
        for value in values:
            slug = str(value or "").strip()
            if not slug or slug in seen:
                continue
            seen.add(slug)
            result.append(slug)
    return result


class ChatBotState(AgentState):
    """智能助手状态，扩展系统内置工具需要写回的交付物列表。"""

    artifacts: NotRequired[list[str]]
    sandbox: NotRequired[dict | None]
    activated_skills: NotRequired[Annotated[list[str], merge_activated_skills]]
