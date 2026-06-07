from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.database_url, echo=False, pool_pre_ping=True)
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


async def init_db() -> None:
    from app.db.models import Base

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all 不会更新已有表，使用幂等语句兼容现有开发数据库。
        await conn.execute(
            text(
                "ALTER TABLE user_selections "
                "ADD COLUMN IF NOT EXISTS knowledge_base_ids JSONB NOT NULL DEFAULT '[]'::jsonb"
            )
        )
