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
        await conn.execute(
            text(
                "ALTER TABLE agent_runs "
                "ADD COLUMN IF NOT EXISTS checkpoint_thread_id VARCHAR(128)"
            )
        )
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS phone VARCHAR(32) NOT NULL DEFAULT ''"))
        await conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS email VARCHAR(255) NOT NULL DEFAULT ''"))
        await conn.execute(
            text("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_object_key VARCHAR(512) NOT NULL DEFAULT ''")
        )
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_not_empty ON users(LOWER(email)) WHERE email <> ''")
        )
        await conn.execute(
            text("ALTER TABLE workspaces ADD COLUMN IF NOT EXISTS is_disabled BOOLEAN NOT NULL DEFAULT FALSE")
        )
        await conn.execute(
            text(
                "CREATE INDEX IF NOT EXISTS idx_agent_runs_checkpoint_thread "
                "ON agent_runs(checkpoint_thread_id)"
            )
        )
        await conn.execute(text("ALTER TABLE user_selections DROP COLUMN IF EXISTS direct_tool_names"))
        await conn.execute(text("ALTER TABLE user_selections DROP COLUMN IF EXISTS direct_mcp_names"))
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_model_providers_provider_id ON model_providers(provider_id)")
        )
        await conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_model_providers_is_enabled ON model_providers(is_enabled)")
        )
        await conn.execute(
            text("CREATE UNIQUE INDEX IF NOT EXISTS ix_model_use_configs_model_use ON model_use_configs(model_use)")
        )
