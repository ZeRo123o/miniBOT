"""Shared PostgreSQL-backed LangGraph checkpointer lifecycle."""

from __future__ import annotations

import asyncio
from urllib.parse import urlsplit, urlunsplit

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import get_settings


class CheckpointManager:
    """Own the pool and saver shared by all compiled agent graphs."""

    def __init__(self) -> None:
        self._pool: AsyncConnectionPool | None = None
        self._saver: AsyncPostgresSaver | None = None
        self._initialization_lock: asyncio.Lock | None = None

    async def initialize(self) -> None:
        """Open the pool and create/migrate LangGraph checkpoint tables once."""
        if self._saver is not None:
            return
        if self._initialization_lock is None:
            self._initialization_lock = asyncio.Lock()
        async with self._initialization_lock:
            if self._saver is not None:
                return
            settings = get_settings()
            pool = AsyncConnectionPool(
                conninfo=_to_psycopg_dsn(settings.database_url),
                kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row},
                min_size=settings.langgraph_checkpoint_pool_min_size,
                max_size=settings.langgraph_checkpoint_pool_max_size,
                open=False,
            )
            await pool.open(wait=True)
            saver = AsyncPostgresSaver(pool)
            try:
                await saver.setup()
            except Exception:
                await pool.close()
                raise
            self._pool = pool
            self._saver = saver

    async def get(self) -> AsyncPostgresSaver:
        """Return the initialized saver; lazy initialization also supports direct runtime use."""
        await self.initialize()
        if self._saver is None:
            raise RuntimeError("LangGraph checkpointer initialization failed.")
        return self._saver

    async def close(self) -> None:
        """Close the underlying PostgreSQL pool during application shutdown."""
        if self._pool is not None:
            await self._pool.close()
        self._pool = None
        self._saver = None


def _to_psycopg_dsn(database_url: str) -> str:
    """Convert SQLAlchemy's asyncpg URL to the PostgreSQL URL psycopg expects."""
    parts = urlsplit(database_url)
    scheme = parts.scheme.split("+", 1)[0]
    if scheme not in {"postgres", "postgresql"}:
        raise ValueError("LangGraph checkpointing requires a PostgreSQL database URL.")
    return urlunsplit(("postgresql", parts.netloc, parts.path, parts.query, parts.fragment))


checkpoint_manager = CheckpointManager()
