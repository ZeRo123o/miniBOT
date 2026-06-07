from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
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


class UserSelection(Base, TimestampMixin):
    __tablename__ = "user_selections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    mcps: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    skills: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    subagents: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    knowledge_base_ids: Mapped[list[int]] = mapped_column(JSONB, default=list, nullable=False)

    __table_args__ = (UniqueConstraint("user_key", name="uq_user_selections_user_key"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "user_key": self.user_key,
            "mcps": self.mcps or [],
            "skills": self.skills or [],
            "subagents": self.subagents or [],
            "knowledge_base_ids": self.knowledge_base_ids or [],
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class KnowledgeBase(Base, TimestampMixin):
    __tablename__ = "knowledge_bases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str] = mapped_column(Text, default="", nullable=False)
    user_key: Mapped[str] = mapped_column(String(128), default="default", nullable=False, index=True)
    metadata_: Mapped[dict[str, Any]] = mapped_column("metadata", JSONB, default=dict, nullable=False)

    documents: Mapped[list["KnowledgeDocument"]] = relationship(
        back_populates="knowledge_base",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    __table_args__ = (UniqueConstraint("user_key", "name", name="uq_knowledge_bases_user_name"),)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "user_key": self.user_key,
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


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_key: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
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
            "user_key": self.user_key,
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
