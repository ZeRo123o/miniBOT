import hashlib
import logging
import re
from pathlib import Path

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.knowledge.chunking import (
    CHUNK_ENGINE_VERSION,
    chunk_markdown,
    normalize_chunk_preset_id,
    resolve_chunk_processing_params,
)
from app.db.repositories import KnowledgeBaseRepository, KnowledgeChunkRepository, KnowledgeDocumentRepository
from app.knowledge.backends import get_knowledge_backend, normalize_knowledge_backend_type
from app.llm.providers.cache import model_cache
from app.storage import get_storage
from app.knowledge.parser import normalize_parser_config, parse_document

logger = logging.getLogger(__name__)
PROCESSING_DOCUMENT_STATUSES = {"uploaded", "parsing", "chunking", "embedding", "indexing"}


class KnowledgeBaseNotFoundError(ValueError):
    """Raised when a knowledge base is missing or inaccessible to the user."""


class DuplicateKnowledgeDocumentError(ValueError):
    """Raised when the same file content already exists in a knowledge base."""


class KnowledgeResourceBusyError(ValueError):
    """Raised when a document or knowledge base still has active processing."""


class KnowledgeService:
    def __init__(self, db: AsyncSession):
        self.base_repo = KnowledgeBaseRepository(db)
        self.document_repo = KnowledgeDocumentRepository(db)
        self.chunk_repo = KnowledgeChunkRepository(db)
        self.storage = get_storage()

    async def list_knowledge_bases(self, user_id: str) -> list[dict]:
        items = await self.base_repo.list(user_id)
        logger.info("Knowledge service listed bases: user_id=%s count=%s", user_id, len(items))
        return [self._knowledge_base_to_dict(item) for item in items]

    async def create_knowledge_base(
        self,
        *,
        name: str,
        description: str = "",
        user_id: str = "default",
        kb_type: str = "milvus",
        chunk_preset_id: str = "general",
        chunk_parser_config: dict | None = None,
        parser_id: str = "auto",
        parser_config: dict | None = None,
        embedding_model_spec: str | None = None,
        extraction_model_spec: str | None = None,
    ) -> dict:
        normalized_kb_type = normalize_knowledge_backend_type(kb_type)
        chunk_params = resolve_chunk_processing_params(chunk_preset_id, chunk_parser_config)
        parser_params = normalize_parser_config(parser_id, parser_config)
        model_metadata = self._validate_knowledge_base_models(
            kb_type=normalized_kb_type,
            embedding_model_spec=embedding_model_spec,
            extraction_model_spec=extraction_model_spec,
        )
        item = await self.base_repo.create(
            name=name,
            description=description,
            user_id=user_id,
            metadata={
                **chunk_params,
                **parser_params,
                "kb_type": normalized_kb_type,
                **model_metadata,
            },
        )
        logger.info(
            "Knowledge service created base: user_id=%s knowledge_base_id=%s name=%s kb_type=%s chunk_preset_id=%s",
            user_id,
            item.id,
            item.name,
            normalized_kb_type,
            chunk_params["chunk_preset_id"],
        )
        return self._knowledge_base_to_dict(item)

    async def list_documents(self, *, knowledge_base_id: int, user_id: str) -> list[dict]:
        knowledge_base = await self.base_repo.get(knowledge_base_id, user_id=user_id)
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError("Knowledge base not found.")
        documents = await self.document_repo.list(knowledge_base_id)
        logger.info(
            "Knowledge service listed documents: user_id=%s knowledge_base_id=%s count=%s",
            user_id,
            knowledge_base_id,
            len(documents),
        )
        return [document.to_dict() for document in documents]

    async def list_chunks(self, *, document_id: int, user_id: str) -> list[dict]:
        document = await self.document_repo.get(document_id)
        if document is None:
            raise ValueError("Knowledge document not found.")
        knowledge_base = await self.base_repo.get(document.knowledge_base_id, user_id=user_id)
        if knowledge_base is None:
            raise ValueError("Knowledge document not found.")

        chunks = await self.chunk_repo.list_by_document(document_id)
        logger.info(
            "Knowledge service listed chunks: user_id=%s document_id=%s count=%s",
            user_id,
            document_id,
            len(chunks),
        )
        return [chunk.to_dict() for chunk in chunks]

    async def delete_document(self, *, document_id: int, user_id: str) -> None:
        """按知识库类型删除后端索引，再删除 PostgreSQL 文档元数据。"""
        document = await self.document_repo.get(document_id)
        if document is None:
            raise ValueError("Knowledge document not found.")
        knowledge_base = await self.base_repo.get(document.knowledge_base_id, user_id=user_id)
        if knowledge_base is None:
            raise ValueError("Knowledge document not found.")
        if document.status in PROCESSING_DOCUMENT_STATUSES:
            raise KnowledgeResourceBusyError("文档正在处理中，暂时无法删除。")

        kb_type = normalize_knowledge_backend_type((knowledge_base.metadata_ or {}).get("kb_type"))
        backend = get_knowledge_backend(kb_type)
        await backend.delete_document(
            knowledge_base_id=knowledge_base.id,
            document_id=document.id,
            knowledge_base_metadata=knowledge_base.metadata_ or {},
        )
        # The document prefix also contains parser-extracted assets. Deleting
        # the complete, hash-scoped prefix avoids leaving orphaned images.
        await self.storage.delete_prefix(self._document_object_prefix(knowledge_base.id, document.file_hash))
        await self.document_repo.delete(document)
        logger.info(
            "Knowledge document deleted: user_id=%s knowledge_base_id=%s document_id=%s backend=%s",
            user_id,
            knowledge_base.id,
            document.id,
            kb_type,
        )

    async def delete_knowledge_base(self, *, knowledge_base_id: int, user_id: str) -> None:
        """Delete backend indexes, stored files, selections, and relational metadata."""
        knowledge_base = await self.base_repo.get(knowledge_base_id, user_id=user_id)
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError("Knowledge base not found.")

        documents = await self.document_repo.list(knowledge_base_id)
        processing_documents = [
            document for document in documents if document.status in PROCESSING_DOCUMENT_STATUSES
        ]
        if processing_documents:
            raise KnowledgeResourceBusyError("知识库中有文档正在处理，暂时无法删除。")

        kb_type = normalize_knowledge_backend_type((knowledge_base.metadata_ or {}).get("kb_type"))
        backend = get_knowledge_backend(kb_type)
        await backend.delete_knowledge_base(
            knowledge_base_id=knowledge_base.id,
            document_ids=[document.id for document in documents],
            knowledge_base_metadata=knowledge_base.metadata_ or {},
        )
        await self.storage.delete_prefix(f"knowledge-bases/{knowledge_base.id}/")
        await self.base_repo.delete_with_selection_cleanup(knowledge_base)
        logger.info(
            "Knowledge base deleted: user_id=%s knowledge_base_id=%s documents=%s backend=%s",
            user_id,
            knowledge_base.id,
            len(documents),
            kb_type,
        )

    async def upload_document(
        self,
        *,
        knowledge_base_id: int,
        user_id: str,
        file: UploadFile,
    ) -> dict:
        knowledge_base = await self.base_repo.get(knowledge_base_id, user_id=user_id)
        if knowledge_base is None:
            raise KnowledgeBaseNotFoundError("Knowledge base not found.")
        if not file.filename:
            raise ValueError("Filename is required.")

        content = await file.read()
        if not content:
            raise ValueError("Uploaded file is empty.")

        filename = Path(file.filename).name
        file_hash = hashlib.sha256(content).hexdigest()
        logger.info(
            "Knowledge document file read: user_id=%s knowledge_base_id=%s filename=%s size=%s hash_prefix=%s",
            user_id,
            knowledge_base_id,
            filename,
            len(content),
            file_hash[:8],
        )
        existing = await self.document_repo.get_by_hash(knowledge_base_id, file_hash)
        if existing is not None:
            logger.warning(
                "Knowledge document duplicate detected: knowledge_base_id=%s document_id=%s hash_prefix=%s",
                knowledge_base_id,
                existing.id,
                file_hash[:8],
            )
            raise DuplicateKnowledgeDocumentError("该文件已存在")

        original_object_key = self._original_object_key(knowledge_base_id, file_hash, filename)
        await self.storage.put_bytes(original_object_key, content, file.content_type)
        logger.info(
            "Knowledge document original saved: knowledge_base_id=%s object_key=%s content_type=%s",
            knowledge_base_id,
            original_object_key,
            file.content_type,
        )

        try:
            document = await self.document_repo.create(
                {
                    "knowledge_base_id": knowledge_base_id,
                    "filename": filename,
                    "content_type": file.content_type or "",
                    "file_size": len(content),
                    "file_hash": file_hash,
                    "status": "uploaded",
                    "original_object_key": original_object_key,
                    "markdown_object_key": "",
                    "metadata_": {},
                }
            )
            logger.info(
                "Knowledge document db record created: knowledge_base_id=%s document_id=%s status=%s",
                knowledge_base_id,
                document.id,
                document.status,
            )
        except IntegrityError:
            existing = await self.document_repo.get_by_hash(knowledge_base_id, file_hash)
            if existing is not None:
                logger.warning(
                    "Knowledge document duplicate detected after integrity error: knowledge_base_id=%s document_id=%s hash_prefix=%s",
                    knowledge_base_id,
                    existing.id,
                    file_hash[:8],
                )
                raise DuplicateKnowledgeDocumentError("该文件已存在")
            logger.exception(
                "Knowledge document db insert failed: knowledge_base_id=%s filename=%s hash_prefix=%s",
                knowledge_base_id,
                filename,
                file_hash[:8],
            )
            raise

        return document.to_dict()

    async def process_document(self, document_id: int) -> None:
        """Parse, chunk, and index an uploaded document in a background task."""
        document = await self.document_repo.get(document_id)
        if document is None:
            logger.warning("Knowledge document background task skipped: document_id=%s not found", document_id)
            return

        knowledge_base = await self.base_repo.get(document.knowledge_base_id)
        if knowledge_base is None:
            logger.warning(
                "Knowledge document background task skipped: document_id=%s knowledge_base_id=%s not found",
                document.id,
                document.knowledge_base_id,
            )
            return

        chunk_params = resolve_chunk_processing_params(
            (knowledge_base.metadata_ or {}).get("chunk_preset_id"),
            (knowledge_base.metadata_ or {}).get("chunk_parser_config"),
        )
        parser_params = normalize_parser_config(
            (knowledge_base.metadata_ or {}).get("parser_id"),
            (knowledge_base.metadata_ or {}).get("parser_config"),
        )
        kb_type = normalize_knowledge_backend_type((knowledge_base.metadata_ or {}).get("kb_type"))
        backend = get_knowledge_backend(kb_type)
        markdown_object_key = self._markdown_object_key(knowledge_base.id, document.file_hash)
        document = await self.document_repo.update_status(document, status="parsing")
        logger.info("Knowledge document status updated: document_id=%s status=parsing", document.id)

        try:
            content = await self.storage.get_bytes(document.original_object_key)
            parsed_document = await parse_document(
                document.filename,
                content,
                content_type=document.content_type,
                parser_id=parser_params["parser_id"],
                parser_config=parser_params["parser_config"],
            )
            markdown = parsed_document.markdown
            asset_records = await self._persist_parsed_assets(
                knowledge_base_id=knowledge_base.id,
                file_hash=document.file_hash,
                parsed_document=parsed_document,
            )
            markdown_bytes = markdown.encode("utf-8")
            logger.info(
                "Knowledge document parsed to markdown: document_id=%s markdown_size=%s",
                document.id,
                len(markdown_bytes),
            )
            await self.storage.put_bytes(
                markdown_object_key,
                markdown_bytes,
                "text/markdown; charset=utf-8",
            )
            logger.info(
                "Knowledge document markdown saved: document_id=%s object_key=%s",
                document.id,
                markdown_object_key,
            )
            document = await self.document_repo.update_status(
                document,
                status="chunking",
                markdown_object_key=markdown_object_key,
                metadata={
                    **(document.metadata_ or {}),
                    "markdown_size": len(markdown_bytes),
                    "parse_result": {
                        **parsed_document.summary(),
                        "assets": asset_records,
                    },
                    "chunk_engine": CHUNK_ENGINE_VERSION,
                    "chunk_preset_id": chunk_params["chunk_preset_id"],
                    "chunk_parser_config": chunk_params["chunk_parser_config"],
                },
            )
            logger.info(
                "Knowledge document status updated: document_id=%s status=chunking",
                document.id,
            )
            chunks = chunk_markdown(
                markdown,
                file_id=str(document.id),
                filename=document.filename,
                preset_id=chunk_params["chunk_preset_id"],
                parser_config=chunk_params["chunk_parser_config"],
            )
            logger.info(
                "Knowledge document chunked: document_id=%s chunks=%s",
                document.id,
                len(chunks),
            )
            await self.chunk_repo.delete_by_document(document.id)
            await self.chunk_repo.bulk_create(
                [
                    {
                        "knowledge_base_id": knowledge_base.id,
                        "document_id": document.id,
                        "chunk_id": chunk["chunk_id"],
                        "chunk_index": chunk["chunk_index"],
                        "content": chunk["content"],
                        "token_count": chunk["token_count"],
                        "start_char_pos": chunk["start_char_pos"],
                        "end_char_pos": chunk["end_char_pos"],
                        "metadata_": {
                            **chunk["metadata"],
                            "content_store": kb_type,
                        },
                    }
                    for chunk in chunks
                ]
            )
            logger.info(
                "Knowledge chunks saved: document_id=%s chunks=%s",
                document.id,
                len(chunks),
            )
            document = await self.document_repo.update_status(
                document,
                status="embedding" if kb_type == "milvus" else "indexing",
                metadata={
                    **(document.metadata_ or {}),
                    "chunk_count": len(chunks),
                    "chunk_engine": CHUNK_ENGINE_VERSION,
                    "chunk_preset_id": chunk_params["chunk_preset_id"],
                    "chunk_parser_config": chunk_params["chunk_parser_config"],
                    "content_store": kb_type,
                    "kb_type": kb_type,
                },
            )
            logger.info(
                "Knowledge document status updated: document_id=%s status=%s",
                document.id,
                document.status,
            )
            index_metadata = await backend.index_document(
                knowledge_base_id=knowledge_base.id,
                document_id=document.id,
                filename=document.filename,
                markdown=markdown,
                chunks=chunks,
                knowledge_base_metadata=knowledge_base.metadata_ or {},
            )
            logger.info(
                "Knowledge document indexed: document_id=%s chunks=%s backend=%s",
                document.id,
                len(chunks),
                kb_type,
            )
            document = await self.document_repo.update_status(
                document,
                status="indexed",
                metadata={
                    **(document.metadata_ or {}),
                    **index_metadata,
                },
            )
            logger.info(
                "Knowledge document status updated: document_id=%s status=indexed",
                document.id,
            )
        except Exception as error:
            logger.exception(
                "Knowledge document parse, chunk, or vector index failed: document_id=%s filename=%s",
                document.id,
                document.filename,
            )
            document = await self.document_repo.update_status(
                document,
                status="failed",
                error_message=str(error),
            )
            logger.info(
                "Knowledge document status updated: document_id=%s status=failed",
                document.id,
            )

    @staticmethod
    def _knowledge_base_to_dict(knowledge_base) -> dict:
        item = knowledge_base.to_dict()
        metadata = item.get("metadata") or {}
        chunk_params = resolve_chunk_processing_params(
            metadata.get("chunk_preset_id"),
            metadata.get("chunk_parser_config"),
        )
        parser_params = normalize_parser_config(
            metadata.get("parser_id"),
            metadata.get("parser_config"),
        )
        item["metadata"] = {
            **metadata,
            **chunk_params,
            **parser_params,
            "kb_type": normalize_knowledge_backend_type(metadata.get("kb_type")),
        }
        item["kb_type"] = item["metadata"]["kb_type"]
        item["chunk_preset_id"] = normalize_chunk_preset_id(chunk_params["chunk_preset_id"])
        item["chunk_parser_config"] = chunk_params["chunk_parser_config"]
        item["parser_id"] = parser_params["parser_id"]
        item["parser_config"] = parser_params["parser_config"]
        return item

    @staticmethod
    def _validate_knowledge_base_models(
        *,
        kb_type: str,
        embedding_model_spec: str | None,
        extraction_model_spec: str | None,
    ) -> dict:
        embedding_model_spec = str(embedding_model_spec or "").strip()
        extraction_model_spec = str(extraction_model_spec or "").strip()
        if not embedding_model_spec:
            raise ValueError("Embedding model is required.")
        embedding_info = model_cache.get_model_info(embedding_model_spec)
        if embedding_info is None or embedding_info.model_type != "embedding":
            raise ValueError("Embedding model is unavailable. Please enable it on the model config page and refresh cache.")

        metadata: dict[str, str] = {"embedding_model_spec": embedding_model_spec}
        if kb_type == "lightrag":
            if not extraction_model_spec:
                raise ValueError("LightRAG extraction model is required.")
            extraction_info = model_cache.get_model_info(extraction_model_spec)
            if extraction_info is None or extraction_info.model_type != "chat":
                raise ValueError("LightRAG extraction model is unavailable. Please select an enabled chat model.")
            metadata["extraction_model_spec"] = extraction_model_spec
        return metadata

    def _original_object_key(self, knowledge_base_id: int, file_hash: str, filename: str) -> str:
        safe_filename = self._safe_filename(filename)
        return f"{self._document_object_prefix(knowledge_base_id, file_hash)}original/{safe_filename}"

    def _markdown_object_key(self, knowledge_base_id: int, file_hash: str) -> str:
        return f"{self._document_object_prefix(knowledge_base_id, file_hash)}parsed/document.md"

    def _document_object_prefix(self, knowledge_base_id: int, file_hash: str) -> str:
        return f"knowledge-bases/{knowledge_base_id}/documents/{file_hash}/"

    async def _persist_parsed_assets(
        self,
        *,
        knowledge_base_id: int,
        file_hash: str,
        parsed_document,
    ) -> list[dict]:
        """Persist parser assets through the storage abstraction.

        Only metadata is returned for PostgreSQL; binary payloads never enter
        document metadata, logs, chunks, or API responses.
        """

        records: list[dict] = []
        for asset in parsed_document.assets:
            if not asset.content:
                continue
            suffix = Path(asset.filename).suffix.lower()
            if not re.fullmatch(r"\.[a-z0-9]{1,10}", suffix):
                suffix = ""
            object_key = (
                f"{self._document_object_prefix(knowledge_base_id, file_hash)}"
                f"assets/{self._safe_filename(asset.asset_id)}{suffix}"
            )
            await self.storage.put_bytes(object_key, asset.content, asset.content_type)
            records.append(
                {
                    "asset_id": asset.asset_id,
                    "kind": asset.kind,
                    "filename": asset.filename,
                    "object_key": object_key,
                    "content_type": asset.content_type,
                    "page_number": asset.page_number,
                    "bbox": asset.bbox,
                    "caption": asset.caption,
                    "metadata": asset.metadata,
                }
            )
            # Release potentially large image payloads after durable storage.
            asset.content = None
        return records

    def _safe_filename(self, filename: str) -> str:
        return re.sub(r"[^A-Za-z0-9._\-\u4e00-\u9fff]", "_", filename).strip("._") or "document"
