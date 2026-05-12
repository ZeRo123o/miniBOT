from typing import Any

from pydantic import BaseModel, Field

from app.plugins.types import PluginResourceOut, SelectionOut


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_key: str = "default"
    conversation_id: int | None = None


class ChatResponse(BaseModel):
    answer: str
    selection: SelectionOut
    resources: dict[str, list[PluginResourceOut]]
    conversation_id: int | None = None


class ConversationCreate(BaseModel):
    user_key: str = Field(default="default", min_length=1, max_length=128)
    title: str = Field(default="新对话", min_length=1, max_length=255)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    archived: bool | None = None


class ConversationMessageCreate(BaseModel):
    role: str = Field(pattern="^(user|assistant|system|tool)$")
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)
