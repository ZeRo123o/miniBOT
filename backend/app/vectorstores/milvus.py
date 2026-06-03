from __future__ import annotations

import asyncio
import logging
from typing import Any

from pymilvus import Collection, CollectionSchema, DataType, FieldSchema, connections, db, utility

from app.vectorstores.base import VectorStore

logger = logging.getLogger(__name__)


class MilvusVectorStore(VectorStore):
    def __init__(
        self,
        *,
        uri: str,
        token: str,
        database: str,
        collection_prefix: str = "kb_",
    ):
        self.uri = uri
        self.token = token
        self.database = database
        self.collection_prefix = collection_prefix
        self.connection_alias = "minibot_milvus"
        self._connected = False

    async def upsert_chunks(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
        dimension: int,
    ) -> None:
        if not chunks:
            return
        if len(chunks) != len(embeddings):
            raise ValueError("Chunk count and embedding count do not match.")

        await asyncio.to_thread(self._upsert_chunks_sync, knowledge_base_id, document_id, chunks, embeddings, dimension)

    async def delete_document_chunks(self, *, knowledge_base_id: int, document_id: int) -> None:
        await asyncio.to_thread(self._delete_document_chunks_sync, knowledge_base_id, document_id)

    def _upsert_chunks_sync(
        self,
        knowledge_base_id: int,
        document_id: int,
        chunks: list[dict[str, Any]],
        embeddings: list[list[float]],
        dimension: int,
    ) -> None:
        collection = self._get_or_create_collection(knowledge_base_id, dimension)
        self._delete_document_chunks_from_collection(collection, document_id)

        rows = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            rows.append(
                {
                    "id": str(chunk["chunk_id"]),
                    "chunk_id": str(chunk["chunk_id"]),
                    "knowledge_base_id": int(knowledge_base_id),
                    "document_id": int(document_id),
                    "chunk_index": int(chunk["chunk_index"]),
                    "content": str(chunk["content"]),
                    "embedding": embedding,
                }
            )

        collection.insert(rows)
        collection.flush()
        collection.load()
        logger.info(
            "Milvus chunks upserted: collection=%s document_id=%s chunks=%s",
            collection.name,
            document_id,
            len(rows),
        )

    def _delete_document_chunks_sync(self, knowledge_base_id: int, document_id: int) -> None:
        collection_name = self._collection_name(knowledge_base_id)
        self._connect()
        if not utility.has_collection(collection_name, using=self.connection_alias):
            return
        collection = Collection(name=collection_name, using=self.connection_alias)
        self._delete_document_chunks_from_collection(collection, document_id)
        collection.flush()

    def _delete_document_chunks_from_collection(self, collection: Collection, document_id: int) -> None:
        expr = f"document_id == {int(document_id)}"
        try:
            collection.delete(expr)
            logger.info("Milvus document chunks deleted: collection=%s document_id=%s", collection.name, document_id)
        except Exception as error:
            message = str(error)
            if "not loaded" in message.lower():
                collection.load()
                collection.delete(expr)
                return
            raise

    def _get_or_create_collection(self, knowledge_base_id: int, dimension: int) -> Collection:
        self._connect()
        collection_name = self._collection_name(knowledge_base_id)
        if utility.has_collection(collection_name, using=self.connection_alias):
            collection = Collection(name=collection_name, using=self.connection_alias)
            self._ensure_dimension(collection, dimension)
            return collection

        fields = [
            FieldSchema(name="id", dtype=DataType.VARCHAR, max_length=255, is_primary=True),
            FieldSchema(name="chunk_id", dtype=DataType.VARCHAR, max_length=255),
            FieldSchema(name="knowledge_base_id", dtype=DataType.INT64),
            FieldSchema(name="document_id", dtype=DataType.INT64),
            FieldSchema(name="chunk_index", dtype=DataType.INT64),
            FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=65535),
            FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dimension),
        ]
        schema = CollectionSchema(
            fields=fields,
            description=f"miniBOT knowledge base {knowledge_base_id} vectors",
        )
        collection = Collection(name=collection_name, schema=schema, using=self.connection_alias)
        collection.create_index(
            "embedding",
            {
                "metric_type": "COSINE",
                "index_type": "IVF_FLAT",
                "params": {"nlist": 1024},
            },
        )
        collection.load()
        logger.info(
            "Milvus collection created: collection=%s dimension=%s",
            collection_name,
            dimension,
        )
        return collection

    def _connect(self) -> None:
        if self._connected:
            return
        connections.connect(alias=self.connection_alias, uri=self.uri, token=self.token)
        try:
            databases = db.list_database(using=self.connection_alias)
            if self.database not in databases:
                db.create_database(self.database, using=self.connection_alias)
            db.using_database(self.database, using=self.connection_alias)
        except Exception as error:
            logger.warning("Milvus database selection failed, using default database: %s", error)
        self._connected = True

    def _collection_name(self, knowledge_base_id: int) -> str:
        return f"{self.collection_prefix}{knowledge_base_id}"

    def _ensure_dimension(self, collection: Collection, dimension: int) -> None:
        for field in collection.schema.fields:
            if field.name == "embedding":
                existing = int(field.params.get("dim") or 0)
                if existing != int(dimension):
                    raise ValueError(
                        f"Milvus collection {collection.name} dimension mismatch: existing={existing}, requested={dimension}."
                    )
                return
