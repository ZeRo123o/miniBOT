from typing import Any, Literal

from pydantic import BaseModel, Field

from app.plugins.types import SelectionOut


class ChatUpload(BaseModel):
    file_name: str
    path: str
    content_type: str = ""
    size: int = 0


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = "default"
    conversation_id: int | None = None
    uploads: list[ChatUpload] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    selection: SelectionOut
    resources: dict[str, list[dict[str, Any]]]
    citations: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    conversation_id: int | None = None
    conversation: dict[str, Any] | None = None
    messages: list[dict[str, Any]] = Field(default_factory=list)


class ConversationCreate(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=128)
    title: str = Field(default="新对话", min_length=1, max_length=255)


class ConversationUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=255)
    archived: bool | None = None


class KnowledgeBaseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str = ""
    user_id: str = Field(default="default", min_length=1, max_length=128)
    kb_type: Literal["milvus", "lightrag"] = "milvus"
    chunk_preset_id: str = Field(default="general", min_length=1, max_length=32)
    chunk_parser_config: dict[str, Any] = Field(default_factory=dict)
