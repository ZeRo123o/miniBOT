from abc import ABC, abstractmethod
from typing import Any


class KnowledgeBackend(ABC):
    """定义不同知识库类型共用的入库、删除和检索接口。"""

    backend_type: str

    @abstractmethod
    async def index_document(
        self,
        *,
        knowledge_base_id: int,
        document_id: int,
        filename: str,
        markdown: str,
        chunks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """把一个已解析文档写入当前知识库后端。"""

    @abstractmethod
    async def delete_document(self, *, knowledge_base_id: int, document_id: int) -> None:
        """删除文档在当前知识库后端中的索引。"""

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
