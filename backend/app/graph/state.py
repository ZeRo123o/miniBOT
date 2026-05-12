from typing import TypedDict

from langchain_core.messages import BaseMessage


class ChatState(TypedDict):
    messages: list[BaseMessage]
    mcps: list[dict]
    skills: list[dict]
    subagents: list[dict]
