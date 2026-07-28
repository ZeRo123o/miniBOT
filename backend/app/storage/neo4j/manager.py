from __future__ import annotations

import logging
import re
import threading
from collections.abc import Callable
from typing import Any

from neo4j import AsyncGraphDatabase

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_SAFE_NEO4J_LABEL_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_shared_neo4j_connection: Neo4jConnectionManager | None = None
_shared_neo4j_connection_lock = threading.Lock()


def safe_neo4j_label(value: str) -> str:
    """校验需要拼接进 Cypher 的标签，参数值仍应使用查询参数传递。"""
    if not _SAFE_NEO4J_LABEL_RE.fullmatch(value or ""):
        raise ValueError(f"非法 Neo4j 标签：{value}")
    return value


async def neo4j_write(driver: Any, query: Callable[..., Any]) -> Any:
    """在异步写事务中执行回调。"""
    async with driver.session() as session:
        return await session.execute_write(query)


async def neo4j_read(driver: Any, cypher: str, **kwargs: Any) -> list[dict[str, Any]]:
    """执行只读 Cypher，并把 Record 转换为普通字典。"""
    async with driver.session() as session:
        result = await session.run(cypher, **kwargs)
        return [record.data() async for record in result]


class Neo4jConnectionManager:
    """延迟创建并复用异步 Neo4j Driver。"""

    def __init__(
        self,
        *,
        uri: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ) -> None:
        settings = get_settings()
        self.uri = uri or settings.neo4j_uri
        self.username = username or settings.neo4j_username
        self.password = settings.neo4j_password if password is None else password
        self._driver: Any = None
        self.status = "closed"

    @property
    def driver(self) -> Any:
        """按需创建 Driver；真实网络连接由首次查询或 connect 建立。"""
        if self._driver is None:
            self._driver = AsyncGraphDatabase.driver(
                self.uri,
                auth=(self.username, self.password),
            )
            self.status = "open"
        return self._driver

    async def connect(self) -> Any:
        """建立连接并主动验证服务可用性。"""
        driver = self.driver
        self.status = "processing"
        try:
            await driver.verify_connectivity()
        except Exception:
            self.status = "closed"
            await driver.close()
            self._driver = None
            logger.exception("Neo4j connection failed: uri=%s", self.uri)
            raise
        self.status = "open"
        return driver

    async def is_connected(self) -> bool:
        if self._driver is None:
            return False
        try:
            await self._driver.verify_connectivity()
            self.status = "open"
            return True
        except Exception:
            self.status = "closed"
            return False

    def is_running(self) -> bool:
        return self.status in {"open", "processing"}

    async def close(self) -> None:
        driver = self._driver
        self._driver = None
        self.status = "closed"
        if driver is not None:
            await driver.close()


def get_shared_neo4j_connection() -> Neo4jConnectionManager:
    """返回进程内共享的连接管理器。"""
    global _shared_neo4j_connection
    if _shared_neo4j_connection is None:
        with _shared_neo4j_connection_lock:
            if _shared_neo4j_connection is None:
                _shared_neo4j_connection = Neo4jConnectionManager()
    return _shared_neo4j_connection


async def close_shared_neo4j_connection() -> None:
    """关闭并清除共享连接，供应用退出阶段调用。"""
    global _shared_neo4j_connection
    manager = _shared_neo4j_connection
    _shared_neo4j_connection = None
    if manager is not None:
        await manager.close()
