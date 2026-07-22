from datetime import datetime
from typing import Any
from urllib.parse import quote

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class Workspace(Base, TimestampMixin):
    __tablename__ = "workspaces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    is_disabled: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    users: Mapped[list["User"]] = relationship(back_populates="workspace")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "created_by": self.created_by,
            "is_disabled": self.is_disabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    username: Mapped[str] = mapped_column(String(128), nullable=False)
    phone: Mapped[str] = mapped_column(String(32), default="", nullable=False)
    email: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    avatar_object_key: Mapped[str] = mapped_column(String(512), default="", nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), default="user", nullable=False, index=True)
    workspace_id: Mapped[int | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True, index=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    workspace: Mapped[Workspace | None] = relationship(back_populates="users")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "uid": self.uid,
            "username": self.username,
            "phone": self.phone,
            "email": self.email,
            "avatar_object_key": self.avatar_object_key,
            "avatar_url": self._avatar_url(),
            "role": self.role,
            "workspace_id": self.workspace_id,
            "workspace_name": self.workspace.name if self.workspace else None,
            "is_deleted": self.is_deleted,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }

    def _avatar_url(self) -> str:
        if not self.avatar_object_key:
            return ""
        version = int(self.updated_at.timestamp()) if self.updated_at else 0
        return f"/api/auth/users/{quote(self.uid, safe='')}/avatar?v={version}"


class PluginResource(Base, TimestampMixin):
    __tablename__ = "plugin_resources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    __table_args__ = (UniqueConstraint("kind", "name", name="uq_plugin_resources_kind_name"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "enabled": self.enabled,
            "config": self.config or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Skill(Base, TimestampMixin):
    """Skill metadata index; complete Skill content remains on disk."""

    __tablename__ = "skills"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    tool_dependencies: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    mcp_dependencies: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    skill_dependencies: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    dir_path: Mapped[str] = mapped_column(String(512), nullable=False)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(64), nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "tool_dependencies": self.tool_dependencies or [],
            "mcp_dependencies": self.mcp_dependencies or [],
            "skill_dependencies": self.skill_dependencies or [],
            "dir_path": self.dir_path,
            "version": self.version,
            "is_builtin": self.is_builtin,
            "content_hash": self.content_hash,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ModelProvider(Base, TimestampMixin):
    """Model provider configuration and its enabled runtime model list."""

    __tablename__ = "model_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider_id: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    provider_type: Mapped[str] = mapped_column(String(32), default="openai", nullable=False)
    default_protocol: Mapped[str | None] = mapped_column(String(64), nullable=True)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    embedding_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rerank_base_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    models_endpoint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    embedding_models_endpoint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rerank_models_endpoint: Mapped[str | None] = mapped_column(String(200), nullable=True)
    api_key_env: Mapped[str | None] = mapped_column(String(128), nullable=True)
    api_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    capabilities: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    enabled_models: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    headers_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    extra_json: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(100), nullable=True)

    def to_dict(self, *, mask_api_key: bool = False) -> dict[str, Any]:
        api_key = self.api_key
        if mask_api_key and api_key:
            api_key = "********"
        return {
            "id": self.id,
            "provider_id": self.provider_id,
            "display_name": self.display_name,
            "provider_type": self.provider_type,
            "default_protocol": self.default_protocol,
            "base_url": self.base_url,
            "embedding_base_url": self.embedding_base_url,
            "rerank_base_url": self.rerank_base_url,
            "models_endpoint": self.models_endpoint,
            "embedding_models_endpoint": self.embedding_models_endpoint,
            "rerank_models_endpoint": self.rerank_models_endpoint,
            "api_key_env": self.api_key_env,
            "api_key": api_key,
            "capabilities": self.capabilities or [],
            "enabled_models": self.enabled_models or [],
            "headers_json": self.headers_json or {},
            "extra_json": self.extra_json or {},
            "is_enabled": self.is_enabled,
            "is_builtin": self.is_builtin,
            "created_by": self.created_by,
            "updated_by": self.updated_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ModelUseConfig(Base, TimestampMixin):
    """Map a named runtime model use to one provider_id:model_id spec."""

    __tablename__ = "model_use_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    model_use: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    model_spec: Mapped[str] = mapped_column(String(512), nullable=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "model_use": self.model_use,
            "model_spec": self.model_spec,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class UserSelection(Base, TimestampMixin):
    __tablename__ = "user_selections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mcps: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    skills: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    subagents: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    knowledge_base_ids: Mapped[list[int]] = mapped_column(JSONB, default=list, nullable=False)

    __table_args__ = (UniqueConstraint("user_id", name="uq_user_selections_user_id"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_id": self.user_id,
            "knowledge_base_ids": self.knowledge_base_ids or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), default="default", nullable=False, index=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    documents: Mapped[list["KnowledgeDocument"]] = relationship(
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_knowledge_bases_user_name"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "user_id": self.user_id,
            "metadata": self.metadata_ or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KnowledgeDocument(Base, TimestampMixin):
    __tablename__ = "knowledge_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="uploaded", nullable=False, index=True)
    original_object_key: Mapped[str] = mapped_column(Text, nullable=False)
    markdown_object_key: Mapped[str] = mapped_column(Text, default="", nullable=False)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    knowledge_base: Mapped[KnowledgeBase] = relationship(back_populates="documents")
    chunks: Mapped[list["KnowledgeChunk"]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (
        UniqueConstraint("knowledge_base_id", "file_hash", name="uq_knowledge_documents_kb_hash"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "knowledge_base_id": self.knowledge_base_id,
            "filename": self.filename,
            "content_type": self.content_type,
            "file_size": self.file_size,
            "file_hash": self.file_hash,
            "status": self.status,
            "original_object_key": self.original_object_key,
            "markdown_object_key": self.markdown_object_key,
            "error_message": self.error_message,
            "metadata": self.metadata_ or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KnowledgeChunk(Base, TimestampMixin):
    __tablename__ = "knowledge_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chunk_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[str] = mapped_column(Text, default="", nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    start_char_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    end_char_pos: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    document: Mapped[KnowledgeDocument] = relationship(back_populates="chunks")

    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_knowledge_chunks_document_index"),
        UniqueConstraint("chunk_id", name="uq_knowledge_chunks_chunk_id"),
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "knowledge_base_id": self.knowledge_base_id,
            "document_id": self.document_id,
            "chunk_id": self.chunk_id,
            "chunk_index": self.chunk_index,
            "token_count": self.token_count,
            "start_char_pos": self.start_char_pos,
            "end_char_pos": self.end_char_pos,
            "metadata": self.metadata_ or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EvaluationDataset(Base, TimestampMixin):
    __tablename__ = "evaluation_datasets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    dataset_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(128), default="default", nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    has_gold_chunks: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    has_gold_answers: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    build_metadata: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    items: Mapped[list["EvaluationDatasetItem"]] = relationship(
        back_populates="dataset",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    runs: Mapped[list["EvaluationRun"]] = relationship(back_populates="dataset")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dataset_id": self.dataset_id,
            "knowledge_base_id": self.knowledge_base_id,
            "user_id": self.user_id,
            "name": self.name,
            "description": self.description,
            "item_count": self.item_count,
            "has_gold_chunks": self.has_gold_chunks,
            "has_gold_answers": self.has_gold_answers,
            "build_metadata": self.build_metadata or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class EvaluationDatasetItem(Base):
    __tablename__ = "evaluation_dataset_items"
    __table_args__ = (
        UniqueConstraint("item_id", name="uq_evaluation_dataset_items_item_id"),
        UniqueConstraint("dataset_id", "item_index", name="uq_evaluation_dataset_items_dataset_index"),
        Index("ix_evaluation_dataset_items_dataset_index", "dataset_id", "item_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    item_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    dataset_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_datasets.dataset_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_base_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    gold_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    gold_answer: Mapped[str | None] = mapped_column(Text, nullable=True)

    dataset: Mapped[EvaluationDataset] = relationship(back_populates="items")


class EvaluationRun(Base):
    __tablename__ = "evaluation_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    knowledge_base_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_bases.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    dataset_id: Mapped[str | None] = mapped_column(
        ForeignKey("evaluation_datasets.dataset_id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    user_id: Mapped[str] = mapped_column(String(128), default="default", nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), default="running", nullable=False, index=True)
    retrieval_config: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    overall_score: Mapped[float | None] = mapped_column(nullable=True)
    total_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_items: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    error_message: Mapped[str] = mapped_column(Text, default="", nullable=False)

    dataset: Mapped[EvaluationDataset | None] = relationship(back_populates="runs")
    items: Mapped[list["EvaluationRunItem"]] = relationship(
        back_populates="run",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "name": self.name,
            "knowledge_base_id": self.knowledge_base_id,
            "dataset_id": self.dataset_id,
            "user_id": self.user_id,
            "status": self.status,
            "retrieval_config": self.retrieval_config or {},
            "metrics": self.metrics or {},
            "overall_score": self.overall_score,
            "total_items": self.total_items,
            "completed_items": self.completed_items,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "error_message": self.error_message,
        }


class EvaluationRunItem(Base):
    __tablename__ = "evaluation_run_items"
    __table_args__ = (
        UniqueConstraint("run_id", "item_index", name="uq_evaluation_run_items_run_index"),
        Index("ix_evaluation_run_items_run_index", "run_id", "item_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(
        ForeignKey("evaluation_runs.run_id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_index: Mapped[int] = mapped_column(Integer, nullable=False)
    dataset_item_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    gold_chunk_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    gold_answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    generated_answer: Mapped[str] = mapped_column(Text, default="", nullable=False)
    retrieved_chunks: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)

    run: Mapped[EvaluationRun] = relationship(back_populates="items")


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), default="新对话", nullable=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)

    messages: Mapped[list["ConversationMessage"]] = relationship(
        back_populates="conversation",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_id": self.user_id,
            "title": self.title,
            "archived": self.archived,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ConversationMessage(Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "role": self.role,
            "content": self.content,
            "metadata": self.metadata_ or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class AgentRun(Base):
    """Persist one parent or subagent execution for audit and task continuation."""

    __tablename__ = "agent_runs"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    thread_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    agent_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    parent_agent_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    run_type: Mapped[str] = mapped_column(String(32), nullable=False, default="chat", index=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    checkpoint_thread_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="created", index=True)
    input_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    result_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(128), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "thread_id": self.thread_id,
            "agent_id": self.agent_id,
            "parent_agent_run_id": self.parent_agent_run_id,
            "run_type": self.run_type,
            "request_id": self.request_id,
            "checkpoint_thread_id": self.checkpoint_thread_id,
            "status": self.status,
            "input_payload": self.input_payload or {},
            "result_payload": self.result_payload or {},
            "error_type": self.error_type,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
