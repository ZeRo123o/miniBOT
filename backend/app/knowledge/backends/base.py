from abc import ABC, abstractmethod
from typing import Any


class KnowledgeBackend(ABC):
    """定义知识库主索引的入库、删除和检索接口。"""

    @abstractmethod
    async def index_document(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        chunks: list[dict[str, Any]],
        knowledge_base_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """把一个已解析文档写入当前知识库后端。"""

    @abstractmethod
    async def delete_document(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
    ) -> None:
        """删除文档在当前知识库后端中的索引。"""

    @abstractmethod
    async def delete_knowledge_base(
        self,
        *,
        knowledge_base_id: int,
    ) -> None:
        """删除一个知识库拥有的全部主索引数据。"""

    @abstractmethod
    async def query(
        self,
        *,
        knowledge_base_id: int,
        query_text: str,
        final_top_k: int,
        recall_top_k: int,
        document_ids: list[int] | None = None,
        **kwargs: Any,
    ) -> list[dict[str, Any]]:
        """检索并返回统一的 content、metadata、score 结果。"""
