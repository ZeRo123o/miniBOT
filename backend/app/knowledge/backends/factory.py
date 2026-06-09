from functools import lru_cache

from app.knowledge.backends.base import KnowledgeBackend
from app.knowledge.backends.lightrag import LightRAGKnowledgeBackend
from app.knowledge.backends.milvus import MilvusKnowledgeBackend

SUPPORTED_KNOWLEDGE_BACKENDS = {"milvus", "lightrag"}


def normalize_knowledge_backend_type(value: str | None) -> str:
    """标准化知识库类型，旧数据默认继续使用 Milvus。"""
    normalized = str(value or "milvus").strip().lower()
    if normalized not in SUPPORTED_KNOWLEDGE_BACKENDS:
        raise ValueError(f"Unsupported knowledge base type: {normalized}")
    return normalized


@lru_cache(maxsize=None)
def get_knowledge_backend(backend_type: str) -> KnowledgeBackend:
    """按类型返回进程内共享的知识库后端实例。"""
    normalized = normalize_knowledge_backend_type(backend_type)
    if normalized == "lightrag":
        return LightRAGKnowledgeBackend()
    return MilvusKnowledgeBackend()
