from typing import Annotated, NotRequired

from app.agents.state import BaseAgentState


def merge_subagent_runs(
    existing: list[dict] | None,
    new: list[dict] | None,
) -> list[dict]:
    """Merge concurrent task updates by child thread, preserving every task run."""
    merged = [dict(item) for item in (existing or [])]
    positions = {
        str(item.get("child_thread_id")): index
        for index, item in enumerate(merged)
        if item.get("child_thread_id")
    }
    for update in new or []:
        item = dict(update)
        thread_id = str(item.get("child_thread_id") or "")
        position = positions.get(thread_id)
        if position is None:
            positions[thread_id] = len(merged)
            merged.append(item)
        else:
            merged[position] = {**merged[position], **item}
    return merged


class ChatBotState(BaseAgentState):
    """主智能体状态，额外维护并行子任务的运行摘要。"""

    subagent_runs: NotRequired[Annotated[list[dict], merge_subagent_runs]]
