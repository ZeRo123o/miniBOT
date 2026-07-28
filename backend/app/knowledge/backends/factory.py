from functools import lru_cache

from app.knowledge.backends.base import KnowledgeBackend
from app.knowledge.backends.milvus import MilvusKnowledgeBackend


@lru_cache(maxsize=1)
def get_knowledge_backend() -> KnowledgeBackend:
    """返回进程内共享的 Milvus 主索引后端。"""
    return MilvusKnowledgeBackend()


async def close_knowledge_backend() -> None:
    """关闭已创建的主索引客户端，不为未使用的进程额外建立连接。"""
    if get_knowledge_backend.cache_info().currsize == 0:
        return
    backend = get_knowledge_backend()
    close = getattr(backend, "close", None)
    if close is not None:
        await close()
    get_knowledge_backend.cache_clear()
