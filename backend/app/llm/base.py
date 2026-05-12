from typing import Protocol

from langchain_core.messages import BaseMessage


class ChatModel(Protocol):
    async def ainvoke(self, messages: list[BaseMessage]) -> BaseMessage:
        """Return the assistant message for the provided conversation messages."""
