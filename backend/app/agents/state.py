"""所有 Agent 图共享的基础状态定义。"""

from typing import Annotated, NotRequired

from langchain.agents import AgentState


def merge_artifacts(existing: list[str] | None, new: list[str] | None) -> list[str]:
    """合并并去重多个工具或子任务写入的交付物路径。"""
    return list(dict.fromkeys([*(existing or []), *(new or [])]))


class BaseAgentState(AgentState):
    """父 Agent 与子 Agent 都需要维护的运行时状态。"""

    artifacts: NotRequired[Annotated[list[str], merge_artifacts]]
    sandbox: NotRequired[dict | None]
    uploads: NotRequired[list[dict]]
    files: NotRequired[dict]
