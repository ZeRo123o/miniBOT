from typing import NotRequired

from langchain.agents import AgentState


class ChatBotState(AgentState):
    """智能助手状态，扩展系统内置工具需要写回的交付物列表。"""

    artifacts: NotRequired[list[str]]
    sandbox: NotRequired[dict | None]
    uploads: NotRequired[list[dict]]
    files: NotRequired[dict]
