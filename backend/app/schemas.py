from typing import Any, Literal

from pydantic import BaseModel, Field

from app.plugins.types import SelectionOut


class ChatUpload(BaseModel):
    file_name: str
    path: str
    content_type: str = ""
    size: int = 0


class InitializeAdminRequest(BaseModel):
    uid: str = Field(min_length=3, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    phone: str = Field(default="", max_length=32)
    email: str = Field(default="", max_length=255)
    password: str = Field(min_length=8, max_length=128)
    workspace_name: str = Field(default="默认工作区", min_length=1, max_length=128)


class LoginRequest(BaseModel):
    login_id: str = Field(min_length=1, max_length=128)
    password: str = Field(min_length=1, max_length=128)


class UserCreate(BaseModel):
    uid: str = Field(min_length=3, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    email: str = Field(default="", max_length=255)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"
    workspace_id: int | None = None


class UserUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    email: str = Field(default="", max_length=255)
    role: Literal["superadmin", "admin", "user"]
    workspace_id: int | None = None


class AccountProfileUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=128)
    phone: str = Field(default="", max_length=32)
    email: str = Field(default="", max_length=255)


class AccountPasswordUpdate(BaseModel):
    old_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    admin_uid: str = Field(min_length=3, max_length=128)
    admin_password: str = Field(min_length=8, max_length=128)


class WorkspaceUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)


class AuthToken(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict[str, Any]


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    user_id: str = "default"
    conversation_id: int | None = None
    model_spec: str | None = None
    request_id: str | None = Field(default=None, min_length=1, max_length=128)
    uploads: list[ChatUpload] = Field(default_factory=list)


class ChatResponse(BaseModel):
    answer: str
    selection: SelectionOut
    resources: dict[str, list[dict[str, Any]]]
    citations: list[dict[str, Any]] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    subagent_runs: list[dict[str, Any]] = Field(default_factory=list)
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
    parser_id: str = Field(default="auto", min_length=1, max_length=64)
    parser_config: dict[str, Any] = Field(default_factory=dict)
    embedding_model_spec: str | None = None
    extraction_model_spec: str | None = None


class KnowledgeQueryTestRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=128)
    query: str = Field(min_length=1)
    search_mode: Literal["vector", "keyword", "hybrid"] = "hybrid"
    final_top_k: int = Field(default=5, ge=1, le=100)
    recall_top_k: int = Field(default=50, ge=1, le=200)
    similarity_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    bm25_top_k: int = Field(default=50, ge=1, le=200)
    vector_weight: float = Field(default=0.7, ge=0.0)
    bm25_weight: float = Field(default=0.3, ge=0.0)
    bm25_drop_ratio_search: float = Field(default=0.0, ge=0.0, le=1.0)
    include_distances: bool = True
    file_name: str | None = None
    use_reranker: bool | None = None
    reranker_model: str | None = None


class KnowledgeQueryConfigRequest(BaseModel):
    user_id: str = Field(default="default", min_length=1, max_length=128)
    search_mode: Literal["vector", "keyword", "hybrid"] = "hybrid"
    final_top_k: int = Field(default=10, ge=1, le=100)
    recall_top_k: int = Field(default=50, ge=1, le=200)
    similarity_threshold: float = Field(default=0.0, ge=0.0, le=1.0)
    bm25_top_k: int = Field(default=50, ge=1, le=200)
    vector_weight: float = Field(default=0.7, ge=0.0)
    bm25_weight: float = Field(default=0.3, ge=0.0)
    bm25_drop_ratio_search: float = Field(default=0.0, ge=0.0, le=1.0)
    use_reranker: bool = False
    reranker_model: str | None = None
